"""Typed ComfyUI capability and safety-contract tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from dcc_mcp_comfyui.bridge import ComfyUIBridge, ComfyUIWorkflowError


def _json_response(payload):
    response = MagicMock()
    response.content = b"{}"
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


@patch("httpx.Client")
def test_catalog_and_runtime_routes_are_typed_and_bounded(mock_client_cls):
    client = MagicMock()
    client.__enter__.return_value = client
    client.get.side_effect = [
        _json_response({"feature_b": False, "feature_a": True}),
        _json_response(["checkpoints", "loras"]),
        _json_response(["z.safetensors", "a.safetensors"]),
        _json_response(["z_embed", "a_embed"]),
        _json_response(
            {
                "system": {
                    "os": "nt",
                    "python_version": "3.12",
                    "pytorch_version": "2.7",
                    "embedded_python": False,
                    "argv": ["C:/private/ComfyUI/main.py"],
                },
                "devices": [{"name": "GPU", "type": "cuda", "index": 0, "vram_total": 10, "vram_free": 5}],
            }
        ),
    ]
    mock_client_cls.return_value = client
    bridge = ComfyUIBridge()

    assert bridge.get_features() == {"feature_a": True, "feature_b": False}
    assert bridge.list_model_folders() == ["checkpoints", "loras"]
    assert bridge.list_models("checkpoints", limit=10) == ["a.safetensors", "z.safetensors"]
    assert bridge.list_embeddings(limit=10) == ["a_embed", "z_embed"]
    runtime = bridge.get_runtime_status()
    assert runtime["system"]["python_version"] == "3.12"
    assert "argv" not in runtime["system"]


def test_node_catalog_returns_summaries_not_unbounded_contracts(monkeypatch):
    bridge = ComfyUIBridge()
    monkeypatch.setattr(
        bridge,
        "get_object_info",
        lambda: {
            "SaveImage": {"display_name": "Save Image", "category": "image", "output_node": True},
            "KSampler": {"display_name": "KSampler", "category": "sampling", "input": {"required": {"huge": {}}}},
        },
    )

    listing = bridge.list_node_types(query="sam", limit=10)
    assert listing == [
        {
            "name": "KSampler",
            "display_name": "KSampler",
            "category": "sampling",
            "output_node": False,
            "deprecated": False,
            "experimental": False,
        }
    ]
    assert "input" not in listing[0]


def test_node_catalog_ignores_non_string_extension_keys(monkeypatch):
    bridge = ComfyUIBridge()
    monkeypatch.setattr(
        bridge,
        "get_object_info",
        lambda: {7: {"category": "invalid"}, "KSampler": {"category": "sampling"}},
    )

    assert [node["name"] for node in bridge.list_node_types()] == ["KSampler"]


def test_cancel_prompt_targets_only_the_exact_running_or_pending_id(monkeypatch):
    bridge = ComfyUIBridge()
    post = MagicMock(side_effect=[{"cancelled": True}, {}])
    monkeypatch.setattr(bridge, "_post", post)
    monkeypatch.setattr(
        bridge,
        "get_queue_status",
        MagicMock(
            side_effect=[
                {"queue_running": [[1, "running-id", {}]], "queue_pending": [[2, "pending-id", {}]]},
                {"queue_running": [], "queue_pending": [[2, "pending-id", {}]]},
                {"queue_running": [], "queue_pending": [[2, "pending-id", {}]]},
                {"queue_running": [], "queue_pending": []},
            ]
        ),
    )

    running = bridge.cancel_prompt("running-id")
    pending = bridge.cancel_prompt("pending-id")

    assert running["action"] == "cancel_running"
    assert running["verified_absent"] is True
    assert pending["action"] == "delete_pending"
    assert pending["verified_absent"] is True
    assert post.call_args_list[0].args == ("/api/jobs/running-id/cancel", {})
    assert post.call_args_list[1].args == ("/queue", {"delete": ["pending-id"]})


def test_cancel_unknown_prompt_is_a_non_mutating_noop(monkeypatch):
    bridge = ComfyUIBridge()
    post = MagicMock()
    monkeypatch.setattr(bridge, "_post", post)
    monkeypatch.setattr(bridge, "get_queue_status", lambda: {"queue_running": [], "queue_pending": []})

    result = bridge.cancel_prompt("unknown-id")

    assert result["action"] == "none"
    assert result["accepted"] is False
    post.assert_not_called()


def test_running_cancel_fails_closed_without_exact_job_api(monkeypatch):
    bridge = ComfyUIBridge()
    monkeypatch.setattr(
        bridge,
        "get_queue_status",
        lambda: {"queue_running": [[1, "running-id", {}]], "queue_pending": []},
    )
    monkeypatch.setattr(
        bridge,
        "_post",
        MagicMock(side_effect=ComfyUIWorkflowError("ComfyUI POST failed (404)")),
    )

    with pytest.raises(ComfyUIWorkflowError, match="404"):
        bridge.cancel_prompt("running-id")


def test_workflow_validation_fails_closed_when_live_catalog_is_unavailable(monkeypatch):
    bridge = ComfyUIBridge()
    monkeypatch.setattr(bridge, "get_object_info", MagicMock(side_effect=OSError("offline")))

    result = bridge.validate_workflow({"1": {"class_type": "EmptyImage", "inputs": {}}})

    assert result["valid"] is False
    assert result["errors"] == ["Could not fetch node contracts from ComfyUI: OSError"]


def test_workflow_validation_rejects_unknown_live_node_class(monkeypatch):
    bridge = ComfyUIBridge()
    monkeypatch.setattr(bridge, "get_object_info", lambda: {})

    result = bridge.validate_workflow({"1": {"class_type": "MissingNode", "inputs": {}}})

    assert result["valid"] is False
    assert result["errors"] == ["Node 1 class_type 'MissingNode' not found in ComfyUI registry"]


def test_delete_history_entry_requires_and_verifies_exact_prompt(monkeypatch):
    bridge = ComfyUIBridge()
    monkeypatch.setattr(bridge, "get_history", MagicMock(side_effect=[{"job-id": {}}, {}]))
    post = MagicMock(return_value={})
    monkeypatch.setattr(bridge, "_post", post)

    result = bridge.delete_history_entry("job-id")

    assert result == {"prompt_id": "job-id", "existed": True, "deleted": True}
    post.assert_called_once_with("/history", {"delete": ["job-id"]})


@patch("httpx.Client")
def test_upload_image_is_bounded_and_returns_content_provenance(mock_client_cls, tmp_path: Path):
    source = tmp_path / "input.png"
    source.write_bytes(b"safe-image-bytes")
    client = MagicMock()
    client.__enter__.return_value = client
    client.post.return_value = _json_response({"name": "input.png", "subfolder": "mcp", "type": "input"})
    mock_client_cls.return_value = client

    result = ComfyUIBridge().upload_image(source, subfolder="mcp", max_file_bytes=1024)

    assert result["name"] == "input.png"
    assert result["source_bytes"] == len(b"safe-image-bytes")
    assert len(result["source_sha256"]) == 64
    _, kwargs = client.post.call_args
    assert kwargs["data"] == {"subfolder": "mcp", "type": "input", "overwrite": "false"}
    assert kwargs["files"]["image"][0] == "input.png"


@patch("httpx.Client")
def test_upload_image_revalidates_server_storage_metadata(mock_client_cls, tmp_path: Path):
    source = tmp_path / "input.png"
    source.write_bytes(b"safe-image-bytes")
    client = MagicMock()
    client.__enter__.return_value = client
    client.post.return_value = _json_response({"name": "input.png", "subfolder": "../escape", "type": "input"})
    mock_client_cls.return_value = client

    with pytest.raises(ComfyUIWorkflowError, match="subfolder"):
        ComfyUIBridge().upload_image(source)


@patch("httpx.Client")
def test_download_artifact_requires_prompt_ownership_and_writes_atomically(mock_client_cls, tmp_path: Path):
    target = tmp_path / "render.png"
    response = MagicMock()
    response.headers = {"content-type": "image/png"}
    response.raise_for_status.return_value = None
    response.iter_bytes.return_value = [b"abc", b"def"]
    stream = MagicMock()
    stream.__enter__.return_value = response
    client = MagicMock()
    client.__enter__.return_value = client
    client.stream.return_value = stream
    mock_client_cls.return_value = client
    bridge = ComfyUIBridge()
    bridge.list_artifacts = MagicMock(
        return_value=[
            {
                "filename": "render.png",
                "subfolder": "",
                "type": "output",
                "node_id": "9",
                "url": "http://127.0.0.1:8188/view?filename=render.png&type=output",
            }
        ]
    )

    result = bridge.download_artifact("job-id", "render.png", target, max_file_bytes=1024)

    assert target.read_bytes() == b"abcdef"
    assert result["bytes"] == 6
    assert result["node_id"] == "9"
    assert len(result["sha256"]) == 64
    assert not target.with_name("render.png.dcc-mcp-part").exists()


def test_artifact_lookup_refuses_filename_not_owned_by_prompt(monkeypatch):
    bridge = ComfyUIBridge()
    monkeypatch.setattr(bridge, "list_artifacts", lambda _prompt_id: [])

    with pytest.raises(ComfyUIWorkflowError, match="exactly one artifact"):
        bridge.resolve_artifact("job-id", "other.png")


def test_artifact_listing_is_shape_based_for_future_media_keys(monkeypatch):
    bridge = ComfyUIBridge()
    monkeypatch.setattr(
        bridge,
        "get_history",
        lambda _prompt_id: {
            "job-id": {
                "outputs": {
                    "12": {
                        "audio": [{"filename": "voice.flac", "subfolder": "audio", "type": "output"}],
                        "localized-custom-key": [{"filename": "scene.glb", "subfolder": "3d", "type": "output"}],
                        "text": ["not a file"],
                    }
                }
            }
        },
    )

    artifacts = bridge.list_artifacts("job-id")

    assert [(item["filename"], item["output_key"]) for item in artifacts] == [
        ("voice.flac", "audio"),
        ("scene.glb", "localized-custom-key"),
    ]


@pytest.mark.parametrize("subfolder", ["../escape", "/absolute", "C:\\absolute"])
def test_upload_subfolder_refuses_traversal(tmp_path: Path, subfolder: str):
    source = tmp_path / "input.png"
    source.write_bytes(b"x")

    with pytest.raises(ComfyUIWorkflowError, match="subfolder"):
        ComfyUIBridge().upload_image(source, subfolder=subfolder)
