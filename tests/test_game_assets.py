"""Recipe binding, fail-closed preflight, and actual HTTP queue handoff."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest

from dcc_mcp_comfyui.bridge import ComfyUIBridge, ComfyUIWorkflowError
from dcc_mcp_comfyui.game_assets import (
    build_asset_workflow,
    generate_asset,
    list_asset_recipes,
    prepare_asset_workflow,
)


# Subset of ComfyUI's nodes.py API contracts, independently specified from the
# recipes. Model enumeration is the test host's installed catalog.
def sd15_contracts():
    def contract(output, **required):
        return {"input": {"required": required}, "output": output}

    return {
        "CheckpointLoaderSimple": contract(["MODEL", "CLIP", "VAE"], ckpt_name=[["v1-5-pruned-emaonly.safetensors"]]),
        "CLIPTextEncode": contract(["CONDITIONING"], clip=["CLIP"], text=["STRING"]),
        "EmptyLatentImage": contract(
            ["LATENT"], width=["INT", {"min": 16, "max": 16384}], height=["INT"], batch_size=["INT"]
        ),
        "KSampler": contract(
            ["LATENT"],
            model=["MODEL"],
            positive=["CONDITIONING"],
            negative=["CONDITIONING"],
            latent_image=["LATENT"],
            seed=["INT"],
            steps=["INT"],
            cfg=["FLOAT"],
            sampler_name=[["euler", "res_multistep"]],
            scheduler=[["normal", "simple"]],
            denoise=["FLOAT"],
        ),
        "VAEDecode": contract(["IMAGE"], samples=["LATENT"], vae=["VAE"]),
        "SaveImage": contract([], images=["IMAGE"], filename_prefix=["STRING"]),
    }


def test_offline_catalog_is_complete_and_has_pinned_setup_metadata():
    recipes = list_asset_recipes()
    assert len(recipes) == 9
    assert len({recipe["id"] for recipe in recipes}) == 9
    for recipe in recipes:
        assert recipe["selection_required"] is True
        assert recipe["execution"] == "local" and not recipe["api_fee"]
        assert recipe["hardware"]["measured_vram_gb"] is None
        assert recipe["download_bytes"] > 0
        assert recipe["setup"] and recipe["license"] and recipe["source"]
        assert "workflow" not in recipe
        for model in recipe["models"].values():
            assert len(model["source_revision"]) == 40
            assert f"/resolve/{model['source_revision']}/" in model["download_url"]
            assert len(model["sha256"]) == 64
            assert model["size_bytes"] > 0
    assert {r["id"] for r in list_asset_recipes("mesh")} == {"hunyuan3d-2", "trellis2-pbr", "pixal3d-pbr"}


@pytest.mark.parametrize("recipe", list_asset_recipes(), ids=lambda r: r["id"])
def test_recipes_are_closed_acyclic_api_graphs_with_reproducible_bindings(recipe):
    parameters = {"prompt": "A blue potion bottle"} if recipe["kind"] == "image" else {"image": "refs/potion.png"}
    if "seed" in recipe["parameters"]:
        parameters["seed"] = 42
    built = build_asset_workflow(recipe["id"], parameters)
    workflow = built["workflow"]
    seen = set()

    def visit(node_id, stack):
        assert node_id not in stack, "cycle"
        if node_id in seen:
            return
        for value in workflow[node_id]["inputs"].values():
            if isinstance(value, list):
                assert len(value) == 2 and type(value[1]) is int and value[1] >= 0
                assert value[0] in workflow
                visit(value[0], stack | {node_id})
        seen.add(node_id)

    outputs = [key for key, value in workflow.items() if value["class_type"] in {"SaveGLB", "SaveImage"}]
    assert len(outputs) == 1
    visit(outputs[0], set())
    assert seen == set(workflow), "unused dependency would inflate requirements"
    assert built == build_asset_workflow(recipe["id"], parameters)
    workflow.clear()
    assert build_asset_workflow(recipe["id"], parameters)["workflow"]


@pytest.mark.parametrize(
    "parameters",
    [
        {},
        {"prompt": ""},
        {"prompt": "x", "seed": True},
        {"prompt": "x", "seed": -1},
        {"prompt": "x", "width": 513},
        {"prompt": "x", "width": 2048, "height": 2048, "batch_size": 2},
        {"prompt": "x", "batch_size": 5},
        {"prompt": "x", "steps": 9999},
        {"prompt": "x", "filename_prefix": "../escape"},
        {"prompt": "x", "filename_prefix": "C:/escape"},
        {"prompt": "x", "filename_prefix": "%date%/escape"},
    ],
)
def test_invalid_requests_never_reach_the_host(parameters):
    bridge = Mock(spec=ComfyUIBridge)
    with pytest.raises(ComfyUIWorkflowError):
        generate_asset(bridge, "sd15", parameters)
    bridge.get_object_info.assert_not_called()
    bridge.submit_workflow.assert_not_called()


@pytest.mark.parametrize(
    "name", ["../x.png", "C:\\x.png", "/x.png", "https://example.test/x.png", "x.png [output]", "x\x00.png"]
)
def test_image_inputs_cannot_escape_comfyui_input(name):
    with pytest.raises(ComfyUIWorkflowError):
        build_asset_workflow("pixal3d-pbr", {"image": name})


def test_no_automatic_recipe_or_model_fallback():
    with pytest.raises(ComfyUIWorkflowError):
        build_asset_workflow("unknown", {"prompt": "x"})
    with pytest.raises(ComfyUIWorkflowError):
        build_asset_workflow("sd15", {"prompt": "x"}, {"diffusion": "wrong.safetensors"})
    with pytest.raises(ComfyUIWorkflowError):
        build_asset_workflow("sd15", {"prompt": "x"}, {"checkpoint": "../model.safetensors"})
    with pytest.raises(ComfyUIWorkflowError):
        list_asset_recipes("unsupported")


@pytest.mark.parametrize(
    "change,code",
    [
        (lambda c: c.pop("KSampler"), "missing_node"),
        (lambda c: c["CheckpointLoaderSimple"]["input"]["required"].update(ckpt_name=[[]]), "missing_model"),
        (
            lambda c: c["CheckpointLoaderSimple"]["input"]["required"].update(ckpt_name=["STRING"]),
            "model_catalog_unavailable",
        ),
        (lambda c: c["KSampler"]["input"]["required"].update(sampler_name=[["other"]]), "unsupported_value"),
        (lambda c: c["KSampler"]["input"]["required"].update(new_required=["INT"]), "missing_required_input"),
        (lambda c: c["CheckpointLoaderSimple"].update(output=["MODEL"]), "unsupported_output_slot"),
        (lambda c: c["CheckpointLoaderSimple"].update(output=["MODEL", "IMAGE", "VAE"]), "incompatible_link"),
        (lambda c: c["EmptyLatentImage"]["input"]["required"].update(width=["INT", {"max": 256}]), "out_of_range"),
        (lambda c: c.update(CheckpointLoaderSimple=None), "missing_node"),
    ],
)
def test_live_contract_changes_block_submission(change, code):
    catalog = sd15_contracts()
    change(catalog)
    bridge = Mock(spec=ComfyUIBridge)
    bridge.get_object_info.return_value = catalog
    result = generate_asset(bridge, "sd15", {"prompt": "x"})
    assert not result["submitted"] and result["prompt_id"] is None
    assert code in {item["code"] for item in result["blockers"]}
    bridge.submit_workflow.assert_not_called()


def test_prepare_is_read_only_and_generation_rechecks_current_models():
    catalog = sd15_contracts()
    bridge = Mock(spec=ComfyUIBridge)
    bridge.get_object_info.return_value = catalog
    assert prepare_asset_workflow(bridge, "sd15", {"prompt": "x"})["ready"]
    bridge.submit_workflow.assert_not_called()
    catalog["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"] = [[]]
    assert not generate_asset(bridge, "sd15", {"prompt": "x"})["submitted"]
    bridge.submit_workflow.assert_not_called()


def test_http_submission_returns_durable_id_and_exact_workflow_provenance(monkeypatch):
    calls = []
    catalog = sd15_contracts()
    catalog["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"] = [["custom/approved.safetensors"]]

    def respond(request):
        calls.append(request)
        if request.url.path == "/object_info":
            return httpx.Response(200, json=catalog)
        assert request.url.path == "/prompt"
        return httpx.Response(200, json={"prompt_id": "asset-job-42", "number": 1, "node_errors": {}})

    client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: client(transport=httpx.MockTransport(respond), **kw))
    result = generate_asset(
        ComfyUIBridge(), "sd15", {"prompt": "blue sword", "seed": 42}, {"checkpoint": "custom/approved.safetensors"}
    )
    assert result["submitted"] and result["prompt_id"] == "asset-job-42"
    assert [r.method for r in calls] == ["GET", "POST"]
    workflow = json.loads(calls[1].content)["prompt"]
    assert workflow["3"]["inputs"]["text"] == "blue sword"
    assert workflow["1"]["inputs"]["ckpt_name"] == "custom/approved.safetensors"
    digest = hashlib.sha256(json.dumps(workflow, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert result["provenance"]["workflow_sha256"] == digest
    assert result["next_tools"]["cancel"] == "comfyui-queue__cancel_prompt"


def test_cutout_preserves_foreground_alpha_and_pbr_uses_same_unwrapped_mesh():
    cutout = build_asset_workflow("birefnet-cutout", {"image": "input.png"})["workflow"]
    assert cutout["4"]["class_type"] == "InvertMask"
    assert cutout["5"]["inputs"]["alpha"] == ["4", 0]
    for recipe in ("trellis2-pbr", "pixal3d-pbr"):
        workflow = build_asset_workflow(recipe, {"image": "input.png", "texture_size": 2048, "target_faces": 12345})[
            "workflow"
        ]
        assert workflow["29"]["inputs"]["mesh"] == workflow["30"]["inputs"]["mesh"] == ["28", 0]
        assert workflow["28"]["inputs"]["resolution"] == workflow["29"]["inputs"]["texture_size"] == 2048
        assert workflow["26"]["inputs"]["target_face_count"] == 12345
    assert workflow["6"]["inputs"]["camera_angle_x"] == ["34", 0]


def test_packaged_entrypoints_keep_failed_preflight_in_error_context(monkeypatch):
    from contextlib import contextmanager

    scripts = Path(__file__).parents[1] / "src/dcc_mcp_comfyui/skills/comfyui-game-assets/scripts"
    bridge = Mock(spec=ComfyUIBridge)
    bridge.get_object_info.return_value = {}

    @contextmanager
    def connected():
        yield bridge

    for name in ("prepare_asset_workflow", "generate_asset"):
        spec = importlib.util.spec_from_file_location(name, scripts / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        monkeypatch.setattr(module, "connected_bridge", connected)
        result = module.main(recipe_id="sd15", parameters={"prompt": "x"})
        assert result["success"] is False
        assert result["context"]["blockers"]
    bridge.submit_workflow.assert_not_called()
