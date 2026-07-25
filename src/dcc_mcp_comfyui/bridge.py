"""ComfyUIBridge — REST + WebSocket client for ComfyUI.

ComfyUI exposes:
- REST API at ``{base_url}/prompt``, ``/history/{id}``, ``/queue``, ``/view``, etc.
- WebSocket at ``ws://{host}:{port}/ws?clientId={client_id}`` for real-time progress.

This bridge provides a typed Python client for the MVP vertical slice:
workflow validate → submit → status/artifact query.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://127.0.0.1:8188"
DEFAULT_TIMEOUT = 120.0
DEFAULT_POLL_INTERVAL = 1.0


class ComfyUINotAvailableError(ConnectionError):
    """Raised when the ComfyUI server is not reachable."""


class ComfyUIWorkflowError(RuntimeError):
    """Raised when a ComfyUI workflow operation fails."""


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
        return sorted(info.keys())

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

        nodes = workflow.get("nodes") or workflow.get("extra_data", {}).get("workflow", {}).get("nodes")

        if not nodes:
            errors.append("No 'nodes' key found in workflow")
            return {"valid": False, "errors": errors, "warnings": warnings, "node_count": 0}

        if not isinstance(nodes, (list, dict)):
            errors.append(f"'nodes' must be a list or dict, got {type(nodes).__name__}")
            return {"valid": False, "errors": errors, "warnings": warnings, "node_count": 0}

        # Get available node types for cross-reference
        try:
            available_types = self.get_node_names()
        except Exception:
            available_types = None
            warnings.append("Could not fetch available node types from ComfyUI; skipped type checking")

        # Validate each node
        node_list = nodes if isinstance(nodes, list) else list(nodes.values())
        seen_ids: set[int] = set()

        for i, node in enumerate(node_list):
            if not isinstance(node, dict):
                errors.append(f"Node at index {i} is not an object")
                continue

            node_id = node.get("id")
            if node_id is None:
                errors.append(f"Node at index {i} has no 'id'")
            elif node_id in seen_ids:
                errors.append(f"Duplicate node id: {node_id}")
            else:
                seen_ids.add(node_id)

            class_type = node.get("class_type")
            if not class_type:
                errors.append(f"Node {node_id or i} has no 'class_type'")
            elif available_types is not None and class_type not in available_types:
                warnings.append(f"Node {node_id} class_type '{class_type}' not found in ComfyUI registry")

        # Check for missing inputs references
        for i, node in enumerate(node_list):
            if not isinstance(node, dict):
                continue
            node_id = node.get("id", i)
            inputs = node.get("inputs", {})
            if isinstance(inputs, dict):
                for input_name, input_value in inputs.items():
                    if isinstance(input_value, list) and len(input_value) >= 2:
                        ref_node_id = input_value[0]
                        if ref_node_id not in seen_ids:
                            errors.append(
                                f"Node {node_id} input '{input_name}' references non-existent node {ref_node_id}"
                            )

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "node_count": len(node_list),
        }

    # -- workflow submission --

    def submit_workflow(self, workflow: dict[str, Any], client_id: Optional[str] = None) -> dict[str, Any]:
        """Submit a workflow to ComfyUI for execution.

        Returns a dict with:
        - ``prompt_id`` (str) — the queued prompt ID
        - ``number`` (int) — queue position
        - ``node_errors`` (dict) — any node-level errors ComfyUI returned
        """
        cid = client_id or self._client_id
        payload = {
            "prompt": workflow,
            "client_id": cid,
        }
        result = self._post("/prompt", json_data=payload)

        prompt_id = result.get("prompt_id")
        if not prompt_id:
            raise ComfyUIWorkflowError(f"ComfyUI /prompt returned no prompt_id: {result}")

        node_errors = result.get("node_errors", {})
        if node_errors:
            logger.warning("ComfyUI /prompt returned node_errors: %s", node_errors)

        return {
            "prompt_id": prompt_id,
            "number": result.get("number", -1),
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

    def get_history(self, prompt_id: str) -> dict[str, Any]:
        """Return the execution history for a prompt."""
        return self._get(f"/history/{prompt_id}")

    def get_prompt_status(self, prompt_id: str) -> dict[str, Any]:
        """Return execution status for a prompt with rich metadata.

        Returns a dict with:
        - ``prompt_id`` (str)
        - ``done`` (bool)
        - ``status`` (str) — "pending", "running", "completed", "error", "not_found"
        - ``outputs`` (dict) — node outputs keyed by node_id
        - ``error_message`` (str or None)
        """
        history = self.get_history(prompt_id)

        if not history or prompt_id not in history:
            return {
                "prompt_id": prompt_id,
                "done": False,
                "status": "not_found",
                "outputs": {},
                "error_message": None,
            }

        entry = history[prompt_id]
        status_data = entry.get("status", {})

        if status_data.get("completed") is False and status_data.get("status_str") == "error":
            return {
                "prompt_id": prompt_id,
                "done": True,
                "status": "error",
                "outputs": {},
                "error_message": status_data.get("messages", [["unknown error"]])[-1][0]
                if status_data.get("messages")
                else "unknown error",
            }

        # Collect outputs from completed nodes
        outputs: dict[str, Any] = {}
        for node_id, node_output in entry.get("outputs", {}).items():
            outputs[node_id] = {
                "images": node_output.get("images", []),
                "gifs": node_output.get("gifs", []),
                "text": node_output.get("text", []),
            }

        return {
            "prompt_id": prompt_id,
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
            "filename": filename,
            "subfolder": subfolder,
            "type": folder_type,
        }
        query = "&".join(f"{k}={v}" for k, v in params.items() if v)
        return f"{self._base_url}/view?{query}"

    def list_artifacts(self, prompt_id: str) -> list[dict[str, Any]]:
        """List all output artifacts for a completed prompt.

        Returns:
            List of dicts with ``filename``, ``subfolder``, ``type``, ``node_id``, ``url``.
        """
        status = self.get_prompt_status(prompt_id)
        artifacts: list[dict[str, Any]] = []

        for node_id, node_outputs in status.get("outputs", {}).items():
            for image in node_outputs.get("images", []):
                if isinstance(image, dict):
                    fn = image.get("filename", "")
                    sf = image.get("subfolder", "")
                    ft = image.get("type", "output")
                    artifacts.append(
                        {
                            "filename": fn,
                            "subfolder": sf,
                            "type": ft,
                            "node_id": node_id,
                            "url": self.get_artifact_url(fn, sf, ft),
                        }
                    )

        return artifacts

    # -- HTTP helpers --

    def _get(self, path: str) -> dict[str, Any]:
        with httpx.Client(timeout=self._timeout) as client:
            try:
                resp = client.get(f"{self._base_url}{path}")
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as exc:
                raise ComfyUIWorkflowError(f"ComfyUI GET {path} failed: {exc.response.status_code}") from exc
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                raise ComfyUINotAvailableError(f"Cannot connect to ComfyUI at {self._base_url}: {exc}") from exc

    def _post(self, path: str, json_data: dict[str, Any]) -> dict[str, Any]:
        with httpx.Client(timeout=self._timeout) as client:
            try:
                resp = client.post(f"{self._base_url}{path}", json=json_data)
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as exc:
                try:
                    body = exc.response.json()
                except Exception:
                    body = exc.response.text
                raise ComfyUIWorkflowError(f"ComfyUI POST {path} failed ({exc.response.status_code}): {body}") from exc
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                raise ComfyUINotAvailableError(f"Cannot connect to ComfyUI at {self._base_url}: {exc}") from exc

    # -- context manager --

    def __enter__(self) -> "ComfyUIBridge":
        self.connect()
        return self

    def __exit__(self, *args: Any) -> None:
        self.disconnect()
