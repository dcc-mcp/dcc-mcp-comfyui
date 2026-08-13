"""ComfyUIBridge — REST + WebSocket client for ComfyUI.

ComfyUI exposes:
- REST API at ``{base_url}/prompt``, ``/history/{id}``, ``/queue``, ``/view``, etc.
- WebSocket at ``ws://{host}:{port}/ws?clientId={client_id}`` for real-time progress.

This bridge provides typed, bounded contracts for workflow execution, queue
control, node/model discovery, runtime diagnostics, and artifact handoff.
"""

from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import os
import re
import time
import uuid
from pathlib import Path, PurePosixPath
from typing import Any, Optional
from urllib.parse import quote, urlencode

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://127.0.0.1:8188"
DEFAULT_TIMEOUT = 120.0
DEFAULT_POLL_INTERVAL = 1.0
DEFAULT_MAX_FILE_BYTES = 512 * 1024 * 1024
MAX_CATALOG_ITEMS = 10_000
MAX_FEATURE_BYTES = 1 * 1024 * 1024
MAX_NODE_CONTRACT_BYTES = 2 * 1024 * 1024
MAX_WORKFLOW_BYTES = 16 * 1024 * 1024
MAX_WORKFLOW_NODES = 4_096
MAX_HTTP_JSON_BYTES = 64 * 1024 * 1024
MAX_STATUS_OUTPUT_NODES = 2_048
MAX_STATUS_ITEMS_PER_KIND = 2_048
MAX_STATUS_TEXT_CHARS = 4_096
MAX_ARTIFACTS = 10_000

_PROMPT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_FOLDER_TYPES = frozenset({"input", "output", "temp"})
_RUNTIME_SYSTEM_FIELDS = (
    "os",
    "python_version",
    "pytorch_version",
    "embedded_python",
    "comfyui_version",
    "required_frontend_version",
    "installed_frontend_version",
    "deploy_environment",
)
_RUNTIME_DEVICE_FIELDS = (
    "name",
    "type",
    "index",
    "vram_total",
    "vram_free",
    "torch_vram_total",
    "torch_vram_free",
)


class ComfyUINotAvailableError(ConnectionError):
    """Raised when the ComfyUI server is not reachable."""


class ComfyUIWorkflowError(RuntimeError):
    """Raised when a ComfyUI workflow operation fails."""


def _require_prompt_id(prompt_id: str) -> str:
    value = str(prompt_id).strip()
    if not _PROMPT_ID_RE.fullmatch(value):
        raise ComfyUIWorkflowError("prompt_id must be a bounded ComfyUI identifier")
    return value


def _bounded_limit(limit: int) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError) as exc:
        raise ComfyUIWorkflowError("limit must be an integer") from exc
    if value < 1 or value > MAX_CATALOG_ITEMS:
        raise ComfyUIWorkflowError(f"limit must be between 1 and {MAX_CATALOG_ITEMS}")
    return value


def _bounded_file_limit(max_file_bytes: int) -> int:
    try:
        value = int(max_file_bytes)
    except (TypeError, ValueError) as exc:
        raise ComfyUIWorkflowError("max_file_bytes must be an integer") from exc
    if value < 1 or value > DEFAULT_MAX_FILE_BYTES:
        raise ComfyUIWorkflowError(f"max_file_bytes must be between 1 and {DEFAULT_MAX_FILE_BYTES}")
    return value


def _require_json_bound(value: Any, *, max_bytes: int, label: str) -> None:
    try:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ComfyUIWorkflowError(f"{label} returned non-JSON data") from exc
    if len(encoded) > max_bytes:
        raise ComfyUIWorkflowError(f"{label} exceeds the bounded response size")


def _bounded_text(value: Any, *, max_chars: int = MAX_STATUS_TEXT_CHARS) -> str:
    text = str(value)
    if len(text) <= max_chars:
        return text
    return f"{text[: max_chars - 1]}…"


def _bounded_file_outputs(value: Any, output_key: str) -> list[dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_STATUS_ITEMS_PER_KIND:
        raise ComfyUIWorkflowError(f"ComfyUI {output_key} output exceeds its bounded contract")
    outputs: list[dict[str, str]] = []
    for candidate in value:
        if not isinstance(candidate, dict) or "filename" not in candidate:
            continue
        outputs.append(
            {
                "filename": _require_filename(str(candidate["filename"])),
                "subfolder": _safe_subfolder(str(candidate.get("subfolder", ""))),
                "type": _require_folder_type(str(candidate.get("type", "output"))),
            }
        )
    return outputs


def _bounded_text_outputs(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_STATUS_ITEMS_PER_KIND:
        raise ComfyUIWorkflowError("ComfyUI text output exceeds its bounded contract")
    return [_bounded_text(item) for item in value]


def _safe_subfolder(subfolder: str) -> str:
    raw = str(subfolder).strip().replace("\\", "/")
    if not raw:
        return ""
    path = PurePosixPath(raw)
    if path.is_absolute() or ":" in raw or any(part in {"", ".", ".."} for part in path.parts):
        raise ComfyUIWorkflowError("subfolder must be a safe relative ComfyUI path")
    if len(raw) > 512:
        raise ComfyUIWorkflowError("subfolder is too long")
    return path.as_posix()


def _require_folder_type(folder_type: str) -> str:
    value = str(folder_type).strip().lower()
    if value not in _FOLDER_TYPES:
        raise ComfyUIWorkflowError("folder_type must be input, output, or temp")
    return value


def _require_catalog_segment(value: str, field_name: str) -> str:
    segment = str(value).strip()
    if (
        not segment
        or len(segment) > 256
        or segment in {".", ".."}
        or any(character in segment for character in ("/", "\\", ":", "\x00"))
    ):
        raise ComfyUIWorkflowError(f"{field_name} must be one bounded catalog name")
    return segment


def _require_filename(filename: str) -> str:
    value = str(filename).strip()
    if (
        not value
        or len(value) > 512
        or value in {".", ".."}
        or PurePosixPath(value).name != value
        or any(character in value for character in ("/", "\\", "\x00"))
    ):
        raise ComfyUIWorkflowError("filename must be one bounded ComfyUI filename")
    return value


def _queue_ids(items: Any) -> list[str]:
    ids: list[str] = []
    if not isinstance(items, list):
        raise ComfyUIWorkflowError("ComfyUI queue entries returned invalid data")
    if len(items) > MAX_CATALOG_ITEMS:
        raise ComfyUIWorkflowError("ComfyUI queue exceeds the bounded item count")
    for item in items:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            value = _require_prompt_id(str(item[1]))
            if value not in ids:
                ids.append(value)
    return ids


class ComfyUIBridge:
    """Typed REST + optional WebSocket client for ComfyUI."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._poll_interval = poll_interval
        self._client_id = str(uuid.uuid4())
        self._connected = False

    # -- properties --

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def client_id(self) -> str:
        return self._client_id

    @property
    def ws_url(self) -> str:
        """WebSocket URL derived from the REST base URL."""
        ws_base = self._base_url.replace("https://", "wss://").replace("http://", "ws://")
        return f"{ws_base}/ws?clientId={self._client_id}"

    # -- connection check --

    def ping(self) -> bool:
        """Check if ComfyUI server is reachable."""
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(f"{self._base_url}/system_stats")
                return resp.is_success
        except Exception:
            return False

    def connect(self) -> None:
        """Verify connectivity to ComfyUI server."""
        if not self.ping():
            raise ComfyUINotAvailableError(
                f"ComfyUI is not reachable at {self._base_url}. Start ComfyUI with --listen and verify the port."
            )
        self._connected = True
        logger.info("ComfyUIBridge connected to %s (client_id=%s)", self._base_url, self._client_id)

    def disconnect(self) -> None:
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    # -- object info (for validation) --

    def get_object_info(self) -> dict[str, Any]:
        """Return ComfyUI node object info for workflow validation."""
        return self._get("/object_info")

    def get_node_names(self) -> list[str]:
        """Return sorted list of available ComfyUI node class names."""
        info = self.get_object_info()
        if not isinstance(info, dict):
            raise ComfyUIWorkflowError("ComfyUI /object_info returned an invalid node catalog")
        return sorted(name for name in info if isinstance(name, str))

    def get_features(self) -> dict[str, Any]:
        """Return the bounded feature manifest advertised by ComfyUI."""
        payload = self._get("/features")
        if not isinstance(payload, dict) or len(payload) > MAX_CATALOG_ITEMS:
            raise ComfyUIWorkflowError("ComfyUI /features returned an invalid manifest")
        if any(not isinstance(key, str) or len(key) > 256 for key in payload):
            raise ComfyUIWorkflowError("ComfyUI /features returned invalid feature names")
        _require_json_bound(payload, max_bytes=MAX_FEATURE_BYTES, label="ComfyUI /features")
        return {key: payload[key] for key in sorted(payload, key=str.casefold)}

    def list_model_folders(self, limit: int = MAX_CATALOG_ITEMS) -> list[str]:
        """List model folder names without exposing filesystem paths."""
        payload = self._get("/models")
        if not isinstance(payload, list):
            raise ComfyUIWorkflowError("ComfyUI /models returned an invalid catalog")
        bounded = _bounded_limit(limit)
        return sorted({str(item) for item in payload if isinstance(item, str)})[:bounded]

    def list_models(self, folder: str, limit: int = 1_000) -> list[str]:
        """List model names in one exact ComfyUI model folder."""
        exact_folder = _require_catalog_segment(folder, "folder")
        payload = self._get(f"/models/{quote(exact_folder, safe='')}")
        if not isinstance(payload, list):
            raise ComfyUIWorkflowError("ComfyUI model route returned an invalid catalog")
        bounded = _bounded_limit(limit)
        return sorted({str(item) for item in payload if isinstance(item, str)})[:bounded]

    def list_embeddings(self, limit: int = 1_000) -> list[str]:
        """List installed embedding names."""
        payload = self._get("/embeddings")
        if not isinstance(payload, list):
            raise ComfyUIWorkflowError("ComfyUI /embeddings returned an invalid catalog")
        bounded = _bounded_limit(limit)
        return sorted({str(item) for item in payload if isinstance(item, str)})[:bounded]

    def get_runtime_status(self) -> dict[str, Any]:
        """Return allowlisted runtime and device diagnostics.

        ComfyUI's raw ``system_stats`` includes process arguments and may
        contain local paths. This public contract deliberately excludes them.
        """
        payload = self._get("/system_stats")
        if not isinstance(payload, dict):
            raise ComfyUIWorkflowError("ComfyUI /system_stats returned invalid data")
        raw_system = payload.get("system", {})
        system = (
            {field: raw_system[field] for field in _RUNTIME_SYSTEM_FIELDS if field in raw_system}
            if isinstance(raw_system, dict)
            else {}
        )
        raw_devices = payload.get("devices", [])
        devices: list[dict[str, Any]] = []
        if isinstance(raw_devices, list):
            for raw_device in raw_devices[:64]:
                if isinstance(raw_device, dict):
                    devices.append(
                        {field: raw_device[field] for field in _RUNTIME_DEVICE_FIELDS if field in raw_device}
                    )
        result = {"system": system, "devices": devices}
        _require_json_bound(result, max_bytes=MAX_FEATURE_BYTES, label="ComfyUI runtime status")
        return result

    def list_node_types(self, query: str = "", category: str = "", limit: int = 200) -> list[dict[str, Any]]:
        """Return bounded node summaries instead of full unbounded contracts."""
        bounded = _bounded_limit(limit)
        query_key = str(query).strip().casefold()
        category_key = str(category).strip().casefold()
        info = self.get_object_info()
        if not isinstance(info, dict):
            raise ComfyUIWorkflowError("ComfyUI /object_info returned an invalid node catalog")
        summaries: list[dict[str, Any]] = []
        for name in sorted(info, key=lambda value: str(value).casefold()):
            contract = info[name]
            if not isinstance(name, str) or not isinstance(contract, dict):
                continue
            display_name = str(contract.get("display_name") or name)
            node_category = str(contract.get("category") or "")
            if query_key and query_key not in f"{name} {display_name}".casefold():
                continue
            if category_key and category_key not in node_category.casefold():
                continue
            summaries.append(
                {
                    "name": name,
                    "display_name": display_name,
                    "category": node_category,
                    "output_node": contract.get("output_node") is True,
                    "deprecated": contract.get("deprecated") is True,
                    "experimental": contract.get("experimental") is True,
                }
            )
            if len(summaries) >= bounded:
                break
        return summaries

    def get_node_type(self, node_class: str) -> dict[str, Any]:
        """Return the exact typed contract for one node class."""
        exact_class = _require_catalog_segment(node_class, "node_class")
        payload = self._get(f"/object_info/{quote(exact_class, safe='')}")
        if not isinstance(payload, dict) or exact_class not in payload:
            raise ComfyUIWorkflowError(f"ComfyUI returned no exact contract for {exact_class!r}")
        contract = payload[exact_class]
        if not isinstance(contract, dict):
            raise ComfyUIWorkflowError(f"ComfyUI returned an invalid contract for {exact_class!r}")
        _require_json_bound(contract, max_bytes=MAX_NODE_CONTRACT_BYTES, label="ComfyUI node contract")
        return {"name": exact_class, "contract": contract}

    # -- workflow validation --

    def validate_workflow(self, workflow: dict[str, Any]) -> dict[str, Any]:
        """Validate a ComfyUI workflow JSON structure.

        Returns a dict with keys:
        - ``valid`` (bool)
        - ``errors`` (list[str])
        - ``warnings`` (list[str])
        - ``node_count`` (int)
        """
        errors: list[str] = []
        warnings: list[str] = []

        if not isinstance(workflow, dict):
            return {"valid": False, "errors": ["Workflow must be a JSON object"], "warnings": [], "node_count": 0}

        if not workflow:
            errors.append("Workflow must contain at least one API-format prompt node")
            return {"valid": False, "errors": errors, "warnings": warnings, "node_count": 0}

        if "nodes" in workflow:
            errors.append("UI workflow format is not executable; export the workflow in API format")
            return {"valid": False, "errors": errors, "warnings": warnings, "node_count": 0}

        if len(workflow) > MAX_WORKFLOW_NODES:
            errors.append(f"Workflow exceeds the {MAX_WORKFLOW_NODES}-node limit")
            return {"valid": False, "errors": errors, "warnings": warnings, "node_count": len(workflow)}

        try:
            _require_json_bound(workflow, max_bytes=MAX_WORKFLOW_BYTES, label="Workflow")
        except ComfyUIWorkflowError as exc:
            errors.append(str(exc))
            return {"valid": False, "errors": errors, "warnings": warnings, "node_count": len(workflow)}

        # Get the live node contracts for class and required-input validation.
        try:
            object_info = self.get_object_info()
        except Exception as exc:
            errors.append(f"Could not fetch node contracts from ComfyUI: {type(exc).__name__}")
            return {"valid": False, "errors": errors, "warnings": warnings, "node_count": len(workflow)}
        if not isinstance(object_info, dict):
            errors.append("ComfyUI /object_info returned an invalid node catalog")
            return {"valid": False, "errors": errors, "warnings": warnings, "node_count": len(workflow)}

        # Validate each node
        node_ids = {str(node_id) for node_id in workflow}

        for node_id, node in workflow.items():
            if not isinstance(node, dict):
                errors.append(f"Node {node_id} is not an object")
                continue

            class_type = node.get("class_type")
            if not isinstance(class_type, str) or not class_type.strip() or len(class_type) > 256:
                errors.append(f"Node {node_id} has no bounded string 'class_type'")
                class_type = None

            inputs = node.get("inputs")
            if not isinstance(inputs, dict):
                errors.append(f"Node {node_id} has no valid 'inputs' object")
                continue

            if class_type:
                node_info = object_info.get(class_type)
                if not isinstance(node_info, dict):
                    errors.append(f"Node {node_id} class_type '{class_type}' not found in ComfyUI registry")
                    continue

                input_contract = node_info.get("input", {})
                required_inputs = input_contract.get("required", {}) if isinstance(input_contract, dict) else {}
                if isinstance(required_inputs, dict):
                    for input_name in required_inputs:
                        if input_name not in inputs:
                            errors.append(f"Node {node_id} is missing required input '{input_name}'")

        # API-format links are [node_id, output_index] pairs.
        for node_id, node in workflow.items():
            if not isinstance(node, dict):
                continue
            inputs = node.get("inputs", {})
            if isinstance(inputs, dict):
                for input_name, input_value in inputs.items():
                    if (
                        isinstance(input_value, list)
                        and len(input_value) == 2
                        and isinstance(input_value[0], (str, int))
                        and isinstance(input_value[1], int)
                        and not isinstance(input_value[1], bool)
                    ):
                        ref_node_id = str(input_value[0])
                        if ref_node_id not in node_ids:
                            errors.append(
                                f"Node {node_id} input '{input_name}' references non-existent node {ref_node_id}"
                            )
                        if input_value[1] < 0:
                            errors.append(f"Node {node_id} input '{input_name}' has a negative output index")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "node_count": len(workflow),
        }

    # -- workflow submission --

    def submit_workflow(self, workflow: dict[str, Any], client_id: Optional[str] = None) -> dict[str, Any]:
        """Submit a workflow to ComfyUI for execution.

        Returns a dict with:
        - ``prompt_id`` (str) — the queued prompt ID
        - ``number`` (int) — queue position
        - ``node_errors`` (dict) — any node-level errors ComfyUI returned
        """
        cid = _require_prompt_id(client_id or self._client_id)
        payload = {
            "prompt": workflow,
            "client_id": cid,
        }
        result = self._post("/prompt", json_data=payload)

        prompt_id = result.get("prompt_id")
        if not prompt_id:
            raise ComfyUIWorkflowError(f"ComfyUI /prompt returned no prompt_id: {result}")
        exact_prompt_id = _require_prompt_id(str(prompt_id))

        node_errors = result.get("node_errors", {})
        if not isinstance(node_errors, dict):
            raise ComfyUIWorkflowError("ComfyUI /prompt returned invalid node_errors")
        _require_json_bound(node_errors, max_bytes=MAX_FEATURE_BYTES, label="ComfyUI node errors")
        if node_errors:
            logger.warning("ComfyUI /prompt returned node_errors: %s", node_errors)

        return {
            "prompt_id": exact_prompt_id,
            "number": int(result.get("number", -1)),
            "node_errors": node_errors,
            "client_id": cid,
        }

    # -- status query --

    def get_queue_status(self) -> dict[str, Any]:
        """Return the current ComfyUI queue state.

        Returns:
            dict with ``queue_running``, ``queue_pending`` lists.
        """
        return self._get("/queue")

    def inspect_queue(self) -> dict[str, Any]:
        """Return prompt identifiers and counts without echoing workflow bodies."""
        queue = self.get_queue_status()
        if not isinstance(queue, dict):
            raise ComfyUIWorkflowError("ComfyUI /queue returned invalid data")
        running_ids = _queue_ids(queue.get("queue_running"))
        pending_ids = _queue_ids(queue.get("queue_pending"))
        return {
            "running_ids": running_ids,
            "pending_ids": pending_ids,
            "running_count": len(running_ids),
            "pending_count": len(pending_ids),
        }

    def cancel_prompt(self, prompt_id: str) -> dict[str, Any]:
        """Interrupt or remove only one exact running/pending prompt."""
        exact_id = _require_prompt_id(prompt_id)
        before = self.inspect_queue()
        if exact_id in before["running_ids"]:
            result = self._post(f"/api/jobs/{quote(exact_id, safe='')}/cancel", {})
            if result.get("cancelled") is not True:
                raise ComfyUIWorkflowError("ComfyUI did not confirm exact running-job cancellation")
            action = "cancel_running"
        elif exact_id in before["pending_ids"]:
            self._post("/queue", {"delete": [exact_id]})
            action = "delete_pending"
        else:
            return {
                "prompt_id": exact_id,
                "action": "none",
                "accepted": False,
                "verified_absent": True,
            }
        after = self.inspect_queue()
        verified_absent = exact_id not in after["running_ids"] and exact_id not in after["pending_ids"]
        return {
            "prompt_id": exact_id,
            "action": action,
            "accepted": True,
            "verified_absent": verified_absent,
        }

    def delete_history_entry(self, prompt_id: str) -> dict[str, Any]:
        """Delete and verify only one exact prompt history entry."""
        exact_id = _require_prompt_id(prompt_id)
        before = self.get_history(exact_id)
        existed = isinstance(before, dict) and exact_id in before
        if existed:
            self._post("/history", {"delete": [exact_id]})
        after = self.get_history(exact_id) if existed else before
        deleted = existed and isinstance(after, dict) and exact_id not in after
        return {"prompt_id": exact_id, "existed": existed, "deleted": deleted}

    def free_memory(self, *, unload_models: bool = False, free_memory: bool = True) -> dict[str, Any]:
        """Request bounded ComfyUI model unloading and/or cache reclamation."""
        if not unload_models and not free_memory:
            raise ComfyUIWorkflowError("at least one memory action must be enabled")
        self._post(
            "/free",
            {"unload_models": bool(unload_models), "free_memory": bool(free_memory)},
        )
        return {"unload_models": bool(unload_models), "free_memory": bool(free_memory), "accepted": True}

    def get_history(self, prompt_id: str) -> dict[str, Any]:
        """Return the execution history for a prompt."""
        exact_id = _require_prompt_id(prompt_id)
        payload = self._get(f"/history/{quote(exact_id, safe='')}")
        if not isinstance(payload, dict):
            raise ComfyUIWorkflowError("ComfyUI history route returned invalid data")
        return payload

    def get_prompt_status(self, prompt_id: str) -> dict[str, Any]:
        """Return execution status for a prompt with rich metadata.

        Returns a dict with:
        - ``prompt_id`` (str)
        - ``done`` (bool)
        - ``status`` (str) — "pending", "running", "completed", "error", "not_found"
        - ``outputs`` (dict) — node outputs keyed by node_id
        - ``error_message`` (str or None)
        """
        exact_id = _require_prompt_id(prompt_id)
        history = self.get_history(exact_id)

        if not history or exact_id not in history:
            return {
                "prompt_id": exact_id,
                "done": False,
                "status": "not_found",
                "outputs": {},
                "error_message": None,
            }

        entry = history[exact_id]
        if not isinstance(entry, dict):
            raise ComfyUIWorkflowError("ComfyUI history entry returned invalid data")
        status_data = entry.get("status", {})
        if not isinstance(status_data, dict):
            raise ComfyUIWorkflowError("ComfyUI prompt status returned invalid data")

        if status_data.get("completed") is False and status_data.get("status_str") == "error":
            messages = status_data.get("messages")
            error_message = "unknown error"
            if isinstance(messages, list) and messages:
                last_message = messages[-1]
                if isinstance(last_message, (list, tuple)) and last_message:
                    error_message = _bounded_text(last_message[0])
                else:
                    error_message = _bounded_text(last_message)
            return {
                "prompt_id": exact_id,
                "done": True,
                "status": "error",
                "outputs": {},
                "error_message": error_message,
            }

        # Collect outputs from completed nodes
        outputs: dict[str, Any] = {}
        raw_outputs = entry.get("outputs", {})
        if not isinstance(raw_outputs, dict):
            raise ComfyUIWorkflowError("ComfyUI history outputs returned invalid data")
        if len(raw_outputs) > MAX_STATUS_OUTPUT_NODES:
            raise ComfyUIWorkflowError("ComfyUI history outputs exceed the bounded node count")
        for node_id, node_output in raw_outputs.items():
            if not isinstance(node_output, dict):
                continue
            outputs[_bounded_text(node_id, max_chars=128)] = {
                "images": _bounded_file_outputs(node_output.get("images"), "images"),
                "gifs": _bounded_file_outputs(node_output.get("gifs"), "gifs"),
                "text": _bounded_text_outputs(node_output.get("text")),
            }

        return {
            "prompt_id": exact_id,
            "done": status_data.get("completed", False),
            "status": "completed" if status_data.get("completed") else "running",
            "outputs": outputs,
            "error_message": None,
        }

    def wait_for_prompt(self, prompt_id: str, timeout: Optional[float] = None) -> dict[str, Any]:
        """Poll until a prompt completes (or timeout).

        Args:
            prompt_id: The prompt ID to wait for.
            timeout: Max seconds to wait (default: bridge timeout).

        Returns:
            Same shape as ``get_prompt_status()``.
        """
        deadline = time.monotonic() + (timeout or self._timeout)

        while time.monotonic() < deadline:
            status = self.get_prompt_status(prompt_id)
            if status["done"]:
                return status
            time.sleep(self._poll_interval)

        # Timeout — check one last time
        status = self.get_prompt_status(prompt_id)
        if not status["done"]:
            status["status"] = "timeout"
        return status

    # -- artifact retrieval --

    def get_artifact_url(self, filename: str, subfolder: str = "", folder_type: str = "output") -> str:
        """Build a download URL for an output artifact.

        Args:
            filename: The output filename (e.g. 'ComfyUI_00001_.png').
            subfolder: Subfolder path within the output directory.
            folder_type: 'output', 'input', or 'temp'.

        Returns:
            Full URL to download the artifact.
        """
        params = {
            "filename": _require_filename(filename),
            "subfolder": _safe_subfolder(subfolder),
            "type": _require_folder_type(folder_type),
        }
        query = urlencode({key: value for key, value in params.items() if value})
        return f"{self._base_url}/view?{query}"

    def list_artifacts(self, prompt_id: str) -> list[dict[str, Any]]:
        """List all file-shaped output artifacts for one exact prompt.

        Returns:
            List of dicts with ``filename``, ``subfolder``, ``type``,
            ``node_id``, ``output_key``, and ``url``. The shape-based scan
            supports current and future image, animation, video, audio, and
            custom-node output keys without a language or media allowlist.
        """
        exact_id = _require_prompt_id(prompt_id)
        history = self.get_history(exact_id)
        entry = history.get(exact_id)
        if entry is None:
            return []
        if not isinstance(entry, dict):
            raise ComfyUIWorkflowError("ComfyUI history entry returned invalid data")
        raw_outputs = entry.get("outputs", {})
        if not isinstance(raw_outputs, dict):
            raise ComfyUIWorkflowError("ComfyUI history outputs returned invalid data")
        if len(raw_outputs) > MAX_STATUS_OUTPUT_NODES:
            raise ComfyUIWorkflowError("ComfyUI history outputs exceed the bounded node count")
        artifacts: list[dict[str, Any]] = []

        for node_id, node_outputs in raw_outputs.items():
            if not isinstance(node_outputs, dict):
                continue
            for output_key, values in node_outputs.items():
                if not isinstance(output_key, str) or not isinstance(values, list):
                    continue
                for candidate in values:
                    if not isinstance(candidate, dict) or "filename" not in candidate:
                        continue
                    filename = _require_filename(str(candidate["filename"]))
                    subfolder = _safe_subfolder(str(candidate.get("subfolder", "")))
                    folder_type = _require_folder_type(str(candidate.get("type", "output")))
                    artifacts.append(
                        {
                            "filename": filename,
                            "subfolder": subfolder,
                            "type": folder_type,
                            "node_id": str(node_id),
                            "output_key": output_key,
                            "url": self.get_artifact_url(filename, subfolder, folder_type),
                        }
                    )
                    if len(artifacts) > MAX_ARTIFACTS:
                        raise ComfyUIWorkflowError("ComfyUI prompt artifacts exceed the bounded item count")

        return artifacts

    def resolve_artifact(
        self,
        prompt_id: str,
        filename: str,
        *,
        subfolder: str = "",
        folder_type: str = "output",
    ) -> dict[str, Any]:
        """Resolve exactly one artifact proven to belong to one prompt."""
        exact_id = _require_prompt_id(prompt_id)
        exact_filename = _require_filename(filename)
        exact_subfolder = _safe_subfolder(subfolder)
        exact_type = _require_folder_type(folder_type)
        matches = [
            artifact
            for artifact in self.list_artifacts(exact_id)
            if artifact.get("filename") == exact_filename
            and _safe_subfolder(str(artifact.get("subfolder", ""))) == exact_subfolder
            and _require_folder_type(str(artifact.get("type", "output"))) == exact_type
        ]
        if len(matches) != 1:
            raise ComfyUIWorkflowError(
                "prompt history must own exactly one artifact matching filename, subfolder, and type"
            )
        return matches[0]

    def upload_image(
        self,
        source: str | Path,
        *,
        subfolder: str = "",
        folder_type: str = "input",
        overwrite: bool = False,
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    ) -> dict[str, Any]:
        """Upload one bounded local image and return content provenance."""
        source_path = Path(source).expanduser()
        if not source_path.is_absolute() or not source_path.is_file():
            raise ComfyUIWorkflowError("source must be an existing absolute regular file")
        exact_subfolder = _safe_subfolder(subfolder)
        exact_type = _require_folder_type(folder_type)
        byte_limit = _bounded_file_limit(max_file_bytes)
        source_bytes = source_path.stat().st_size
        if source_bytes > byte_limit:
            raise ComfyUIWorkflowError(f"source exceeds max_file_bytes ({source_bytes} > {byte_limit})")
        digest = hashlib.sha256()
        with source_path.open("rb") as source_file:
            for block in iter(lambda: source_file.read(1024 * 1024), b""):
                digest.update(block)
            source_file.seek(0)
            result = self._post_multipart(
                "/upload/image",
                data={
                    "subfolder": exact_subfolder,
                    "type": exact_type,
                    "overwrite": str(bool(overwrite)).lower(),
                },
                files={
                    "image": (
                        _require_filename(source_path.name),
                        source_file,
                        mimetypes.guess_type(source_path.name)[0] or "application/octet-stream",
                    )
                },
            )
        if not isinstance(result, dict):
            raise ComfyUIWorkflowError("ComfyUI upload route returned invalid data")
        uploaded_name = _require_filename(str(result.get("name") or source_path.name))
        uploaded_subfolder = _safe_subfolder(str(result.get("subfolder") or exact_subfolder))
        uploaded_type = _require_folder_type(str(result.get("type") or exact_type))
        return {
            "name": uploaded_name,
            "subfolder": uploaded_subfolder,
            "type": uploaded_type,
            "source_bytes": source_bytes,
            "source_sha256": digest.hexdigest(),
        }

    def download_artifact(
        self,
        prompt_id: str,
        filename: str,
        target: str | Path,
        *,
        subfolder: str = "",
        folder_type: str = "output",
        overwrite: bool = False,
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    ) -> dict[str, Any]:
        """Download one prompt-owned artifact through a bounded atomic write."""
        artifact = self.resolve_artifact(
            prompt_id,
            filename,
            subfolder=subfolder,
            folder_type=folder_type,
        )
        target_path = Path(target).expanduser()
        if not target_path.is_absolute() or not target_path.parent.is_dir():
            raise ComfyUIWorkflowError("target must be an absolute path in an existing directory")
        if target_path.exists() and not overwrite:
            raise ComfyUIWorkflowError("target already exists; set overwrite=true to replace it")
        byte_limit = _bounded_file_limit(max_file_bytes)
        partial = target_path.with_name(f"{target_path.name}.dcc-mcp-part")
        if partial.exists():
            raise ComfyUIWorkflowError("bounded partial target already exists")
        digest = hashlib.sha256()
        total = 0
        try:
            with httpx.Client(timeout=self._timeout) as client:
                with client.stream("GET", str(artifact["url"])) as response:
                    response.raise_for_status()
                    with partial.open("xb") as output:
                        for block in response.iter_bytes():
                            total += len(block)
                            if total > byte_limit:
                                raise ComfyUIWorkflowError(f"artifact exceeds max_file_bytes ({total} > {byte_limit})")
                            digest.update(block)
                            output.write(block)
            if overwrite:
                partial.replace(target_path)
            else:
                try:
                    os.link(partial, target_path)
                except FileExistsError as exc:
                    raise ComfyUIWorkflowError("target appeared during download; refusing to overwrite it") from exc
                partial.unlink()
        except httpx.HTTPStatusError as exc:
            raise ComfyUIWorkflowError(f"ComfyUI artifact download failed: {exc.response.status_code}") from exc
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise ComfyUINotAvailableError(f"Cannot connect to ComfyUI at {self._base_url}: {exc}") from exc
        finally:
            if partial.exists():
                partial.unlink()
        return {
            "prompt_id": _require_prompt_id(prompt_id),
            "filename": artifact["filename"],
            "subfolder": artifact.get("subfolder", ""),
            "type": artifact.get("type", "output"),
            "node_id": artifact.get("node_id"),
            "bytes": total,
            "sha256": digest.hexdigest(),
            "target": str(target_path),
        }

    # -- HTTP helpers --

    def _get(self, path: str) -> Any:
        with httpx.Client(timeout=self._timeout) as client:
            try:
                resp = client.get(f"{self._base_url}{path}")
                resp.raise_for_status()
                if len(resp.content) > MAX_HTTP_JSON_BYTES:
                    raise ComfyUIWorkflowError(f"ComfyUI GET {path} exceeds the bounded response size")
                try:
                    return resp.json()
                except ValueError as exc:
                    raise ComfyUIWorkflowError(f"ComfyUI GET {path} returned invalid JSON") from exc
            except httpx.HTTPStatusError as exc:
                raise ComfyUIWorkflowError(f"ComfyUI GET {path} failed: {exc.response.status_code}") from exc
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                raise ComfyUINotAvailableError(f"Cannot connect to ComfyUI at {self._base_url}: {exc}") from exc

    def _post(self, path: str, json_data: dict[str, Any]) -> dict[str, Any]:
        with httpx.Client(timeout=self._timeout) as client:
            try:
                resp = client.post(f"{self._base_url}{path}", json=json_data)
                resp.raise_for_status()
                if not resp.content:
                    return {}
                if len(resp.content) > MAX_HTTP_JSON_BYTES:
                    raise ComfyUIWorkflowError(f"ComfyUI POST {path} exceeds the bounded response size")
                try:
                    payload = resp.json()
                except ValueError as exc:
                    raise ComfyUIWorkflowError(f"ComfyUI POST {path} returned invalid JSON") from exc
                if not isinstance(payload, dict):
                    raise ComfyUIWorkflowError(f"ComfyUI POST {path} returned invalid data")
                return payload
            except httpx.HTTPStatusError as exc:
                raise ComfyUIWorkflowError(f"ComfyUI POST {path} failed ({exc.response.status_code})") from exc
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                raise ComfyUINotAvailableError(f"Cannot connect to ComfyUI at {self._base_url}: {exc}") from exc

    def _post_multipart(
        self,
        path: str,
        *,
        data: dict[str, str],
        files: dict[str, tuple[str, Any, str]],
    ) -> dict[str, Any]:
        with httpx.Client(timeout=self._timeout) as client:
            try:
                resp = client.post(f"{self._base_url}{path}", data=data, files=files)
                resp.raise_for_status()
                try:
                    payload = resp.json() if resp.content else {}
                except ValueError as exc:
                    raise ComfyUIWorkflowError("ComfyUI upload route returned invalid JSON") from exc
                if not isinstance(payload, dict):
                    raise ComfyUIWorkflowError("ComfyUI upload route returned invalid data")
                return payload
            except httpx.HTTPStatusError as exc:
                raise ComfyUIWorkflowError(f"ComfyUI POST {path} failed ({exc.response.status_code})") from exc
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                raise ComfyUINotAvailableError(f"Cannot connect to ComfyUI at {self._base_url}: {exc}") from exc

    # -- context manager --

    def __enter__(self) -> "ComfyUIBridge":
        self.connect()
        return self

    def __exit__(self, *args: Any) -> None:
        self.disconnect()
