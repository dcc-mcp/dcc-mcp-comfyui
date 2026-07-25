"""Validate a ComfyUI workflow JSON against the running instance.

Usage: called as a skill script by dcc-mcp-core with kwargs from tools.yaml.
"""

from __future__ import annotations

from typing import Any

from dcc_mcp_comfyui.api import cf_success, get_bridge, with_comfyui


@with_comfyui
def run(**kwargs: Any) -> dict:
    workflow = kwargs.get("workflow")
    if not workflow:
        return cf_success(
            "No workflow provided",
            valid=False,
            errors=["workflow parameter is required"],
            warnings=[],
            node_count=0,
        )

    bridge = get_bridge()
    result = bridge.validate_workflow(workflow)

    return cf_success(
        f"Workflow validation {'passed' if result['valid'] else 'failed'}",
        **result,
    )
