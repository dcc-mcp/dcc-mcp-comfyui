"""Query execution status and outputs for a submitted ComfyUI prompt.

Usage: called as a skill script by dcc-mcp-core with kwargs from tools.yaml.
"""

from __future__ import annotations

from typing import Any

from dcc_mcp_comfyui.api import cf_success, get_bridge, with_comfyui


@with_comfyui
def run(**kwargs: Any) -> dict:
    prompt_id = kwargs.get("prompt_id")
    if not prompt_id:
        return cf_success(
            "No prompt_id provided",
            prompt_id=None,
            done=False,
            status="error",
            outputs={},
            error_message="prompt_id parameter is required",
        )

    bridge = get_bridge()
    status = bridge.get_prompt_status(prompt_id)

    # Collect artifact list if done
    artifacts = []
    if status["done"] and status["status"] == "completed":
        artifacts = bridge.list_artifacts(prompt_id)

    return cf_success(
        f"Job {prompt_id}: {status['status']}",
        prompt_id=prompt_id,
        done=status["done"],
        status=status["status"],
        outputs=status.get("outputs", {}),
        error_message=status.get("error_message"),
        artifacts=artifacts,
    )
