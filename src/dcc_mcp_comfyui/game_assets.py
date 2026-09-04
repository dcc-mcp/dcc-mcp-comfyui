"""Curated local game-asset workflows and live dependency preflight.

Recipes are package data, never downloaded or executed as Python. ComfyUI owns
inference and durable jobs; the existing bridge owns transport and artifacts.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from copy import deepcopy
from importlib.resources import files
from typing import Any

from dcc_mcp_comfyui.bridge import ComfyUIBridge, ComfyUIWorkflowError

_KINDS = ("all", "image", "cutout", "mesh")
_INTEGER_LIMITS = {
    "width": (256, 2048),
    "height": (256, 2048),
    "batch_size": (1, 4),
    "seed": (0, 2**53 - 1),
    "target_faces": (1000, 200000),
    "texture_size": (512, 2048),
}


def _catalog() -> list[dict[str, Any]]:
    return json.loads(files("dcc_mcp_comfyui").joinpath("recipes", "game_assets.json").read_text(encoding="utf-8"))


def _recipe(recipe_id: str) -> dict[str, Any]:
    for recipe in _catalog():
        if recipe["id"] == recipe_id:
            return recipe
    raise ComfyUIWorkflowError("Unknown recipe_id; use list_asset_recipes")


def _summary(recipe: dict[str, Any]) -> dict[str, Any]:
    result = {key: value for key, value in recipe.items() if key not in {"workflow", "bindings"}}
    result["parameters"] = {
        name: recipe["workflow"][targets[0][0]]["inputs"][targets[0][1]] for name, targets in recipe["bindings"].items()
    }
    result["required_nodes"] = sorted({node["class_type"] for node in recipe["workflow"].values()})
    result["download_bytes"] = sum(model.get("size_bytes") or 0 for model in recipe["models"].values())
    return result


def list_asset_recipes(kind: str = "all") -> list[dict[str, Any]]:
    """Return an offline catalog, including exact defaults and setup sources."""
    if kind not in _KINDS:
        raise ComfyUIWorkflowError(f"kind must be one of {_KINDS}")
    return [_summary(recipe) for recipe in _catalog() if kind == "all" or recipe["kind"] == kind]


def _relative_name(value: Any, label: str) -> str:
    # Accept model subdirectories and uploaded input names on both platforms.
    if not isinstance(value, str) or not 1 <= len(value) <= 240:
        raise ComfyUIWorkflowError(f"{label} must be a bounded relative ComfyUI name")
    value = value.replace("\\", "/")
    if any(ord(char) < 32 for char in value) or any(char in value for char in ':*?"<>|%[]'):
        raise ComfyUIWorkflowError(f"{label} contains unsupported characters")
    if any(part in {"", ".", ".."} or part.endswith((" ", ".")) for part in value.split("/")):
        raise ComfyUIWorkflowError(f"{label} must stay within its ComfyUI folder")
    return value


def build_asset_workflow(
    recipe_id: str,
    parameters: dict[str, Any] | None = None,
    models: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Bind only declared parameters; validate direct Python calls too."""
    recipe = _recipe(recipe_id)
    parameters = {} if parameters is None else parameters
    models = {} if models is None else models
    if not isinstance(parameters, dict) or not isinstance(models, dict):
        raise ComfyUIWorkflowError("parameters and models must be objects")
    if parameters.keys() - recipe["bindings"].keys():
        raise ComfyUIWorkflowError("Unsupported parameter for this recipe; inspect list_asset_recipes")
    if models.keys() - recipe["models"].keys():
        raise ComfyUIWorkflowError("Unknown model slot; inspect list_asset_recipes")
    workflow = deepcopy(recipe["workflow"])
    resolved = {}
    for name, targets in recipe["bindings"].items():
        value = parameters.get(name, workflow[targets[0][0]]["inputs"][targets[0][1]])
        if name in _INTEGER_LIMITS:
            low, high = _INTEGER_LIMITS[name]
            if type(value) is not int or not low <= value <= high:
                raise ComfyUIWorkflowError(f"{name} must be an integer between {low} and {high}")
            if name in {"width", "height"} and value % 16:
                raise ComfyUIWorkflowError(f"{name} must be a multiple of 16")
            if name == "texture_size" and value not in {512, 1024, 2048}:
                raise ComfyUIWorkflowError("texture_size must be 512, 1024, or 2048")
        elif name in {"prompt", "negative_prompt"}:
            if not isinstance(value, str) or len(value) > 8000 or "\x00" in value:
                raise ComfyUIWorkflowError(f"{name} must be a string of at most 8000 characters")
            if name == "prompt" and not value.strip():
                raise ComfyUIWorkflowError("prompt is required for image generation")
        else:
            value = _relative_name(value, name)
            if name == "filename_prefix" and not re.fullmatch(r"[A-Za-z0-9_/-]+", value):
                raise ComfyUIWorkflowError("filename_prefix accepts only letters, digits, slash, dash and underscore")
        resolved[name] = value
        for node_id, input_name in targets:
            workflow[node_id]["inputs"][input_name] = value
    if resolved.get("width", 1024) * resolved.get("height", 1024) * resolved.get("batch_size", 1) > 4 * 1024**2:
        raise ComfyUIWorkflowError("Requested batch exceeds the 4 megapixel total budget")
    selected_models = {}
    for slot, model in recipe["models"].items():
        selected = _relative_name(models.get(slot, model["filename"]), f"models.{slot}")
        workflow[model["node"]]["inputs"][model["input"]] = selected
        selected_models[slot] = selected
    digest = hashlib.sha256(json.dumps(workflow, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        "recipe": _summary(recipe),
        "workflow": workflow,
        "provenance": {
            "recipe_id": recipe_id,
            "recipe_revision": recipe["revision"],
            "workflow_sha256": digest,
            "models": selected_models,
            "parameters": resolved,
        },
    }


def _choices(spec: list) -> list | None:
    if isinstance(spec[0], list):
        return spec[0]
    if spec[0] == "COMBO" and len(spec) > 1 and isinstance(spec[1], dict):
        return spec[1].get("options")
    if spec[0] == "COMFY_DYNAMICCOMBO_V3" and len(spec) > 1 and isinstance(spec[1], dict):
        options = spec[1].get("options", [])
        if isinstance(options, list) and all(isinstance(option, dict) and "key" in option for option in options):
            return [option["key"] for option in options]
    return None


def _check_contracts(workflow: dict, catalog: dict, models: dict) -> list[dict[str, str]]:
    """Check a single live snapshot; never infer missing models from filenames."""
    blockers = []
    model_inputs = {(model["node"], model["input"]): slot for slot, model in models.items()}

    def block(code: str, node_id: str, field: str = "") -> None:
        item = {"code": code, "node_id": node_id, "node_class": workflow[node_id]["class_type"], "input": field}
        slot = model_inputs.get((node_id, field))
        if slot:
            item.update(
                model_slot=slot, filename=workflow[node_id]["inputs"][field], directory=models[slot]["directory"]
            )
        blockers.append(item)

    for node_id, node in workflow.items():
        contract = catalog.get(node["class_type"])
        if not isinstance(contract, dict):
            block("missing_node", node_id)
            continue
        inputs = contract.get("input")
        if (
            not isinstance(inputs, dict)
            or not isinstance(inputs.get("required", {}), dict)
            or not isinstance(inputs.get("optional", {}), dict)
        ):
            block("invalid_node_contract", node_id)
            continue
        specs = {**inputs.get("required", {}), **inputs.get("optional", {})}
        for field in inputs.get("required", {}):
            if field not in node["inputs"]:
                block("missing_required_input", node_id, field)
        for field, value in node["inputs"].items():
            spec = specs.get(field)
            if not isinstance(spec, (list, tuple)) or not spec:
                block("unsupported_input", node_id, field)
                continue
            if isinstance(value, list):
                upstream = workflow.get(value[0], {})
                upstream_contract = catalog.get(upstream.get("class_type"))
                output_types = upstream_contract.get("output", []) if isinstance(upstream_contract, dict) else []
                if not isinstance(output_types, list) or len(output_types) <= value[1]:
                    block("unsupported_output_slot", node_id, field)
                elif isinstance(spec[0], str) and output_types[value[1]] not in spec[0].split(",") and spec[0] != "*":
                    block("incompatible_link", node_id, field)
                continue
            choices = _choices(spec)
            if node["class_type"] == "LoadImage" and field == "image":
                # This widget's options may omit uploaded files in subfolders.
                # ComfyUI's VALIDATE_INPUTS owns the final existence check.
                continue
            if spec[0] == "COMFY_DYNAMICCOMBO_V3" and isinstance(choices, list) and value in choices:
                selected = next(option for option in spec[1]["options"] if option["key"] == value)
                if selected.get("inputs", {}).get("required"):
                    block("unsupported_dynamic_inputs", node_id, field)
            if (node_id, field) in model_inputs and not isinstance(choices, list):
                block("model_catalog_unavailable", node_id, field)
            elif isinstance(choices, list) and value not in choices:
                code = "missing_model" if (node_id, field) in model_inputs else "unsupported_value"
                block(code, node_id, field)
            elif isinstance(spec[0], str) and spec[0] in {"INT", "FLOAT"}:
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    block("invalid_number", node_id, field)
                elif spec[0] == "INT" and type(value) is not int:
                    block("invalid_integer", node_id, field)
                elif len(spec) > 1 and isinstance(spec[1], dict):
                    if value < spec[1].get("min", -math.inf) or value > spec[1].get("max", math.inf):
                        block("out_of_range", node_id, field)
            elif spec[0] in ("STRING", "BOOLEAN"):
                expected = str if spec[0] == "STRING" else bool
                if type(value) is not expected:
                    block("invalid_literal", node_id, field)
            elif spec[0] == "COLOR":
                if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
                    block("invalid_color", node_id, field)
            elif choices is None:
                block("unsupported_literal_type", node_id, field)
    return blockers


def prepare_asset_workflow(
    bridge: ComfyUIBridge,
    recipe_id: str,
    parameters: dict[str, Any] | None = None,
    models: dict[str, str] | None = None,
) -> dict[str, Any]:
    result = build_asset_workflow(recipe_id, parameters, models)
    catalog = bridge.get_object_info()
    if not isinstance(catalog, dict):
        raise ComfyUIWorkflowError("ComfyUI returned an invalid node catalog")
    blockers = _check_contracts(result["workflow"], catalog, result["recipe"]["models"])
    result.update(
        ready=not blockers,
        blockers=blockers,
        readiness_scope="Node contracts and installed model names only; input-image existence, GPU execution and output quality are unverified.",
    )
    return result


def generate_asset(
    bridge: ComfyUIBridge,
    recipe_id: str,
    parameters: dict[str, Any] | None = None,
    models: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Preflight immediately before one submission; never wait or retry inference."""
    prepared = prepare_asset_workflow(bridge, recipe_id, parameters, models)
    if not prepared["ready"]:
        return {**prepared, "submitted": False, "prompt_id": None}
    job = bridge.submit_workflow(prepared["workflow"])
    return {
        **job,
        "submitted": True,
        "provenance": prepared["provenance"],
        "next_tools": {
            "status": "comfyui-workflow__query_job_status",
            "cancel": "comfyui-queue__cancel_prompt",
            "download": "comfyui-assets__download_artifact",
        },
    }
