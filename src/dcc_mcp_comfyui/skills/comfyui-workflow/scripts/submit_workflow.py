"""Submit a workflow JSON to ComfyUI for execution.

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
            prompt_id=None,
            number=-1,
            node_errors={},
            error="workflow parameter is required",
        )

    wait = kwargs.get("wait", False)
    timeout = kwargs.get("timeout", 120)

    bridge = get_bridge()

    # Validate first
    validation = bridge.validate_workflow(workflow)
    if not validation["valid"]:
        return cf_success(
            "Workflow validation failed — not submitted",
            prompt_id=None,
            number=-1,
            node_errors={},
            validation=validation,
        )

    # Submit
    result = bridge.submit_workflow(workflow)
    prompt_id = result["prompt_id"]

    if wait:
        status = bridge.wait_for_prompt(prompt_id, timeout=timeout)
        return cf_success(
            f"Workflow submitted and completed: {status['status']}",
            prompt_id=prompt_id,
            number=result["number"],
            node_errors=result["node_errors"],
            status=status["status"],
            outputs=status.get("outputs", {}),
            error_message=status.get("error_message"),
        )

    return cf_success(
        "Workflow submitted to ComfyUI queue",
        prompt_id=prompt_id,
        number=result["number"],
        node_errors=result["node_errors"],
        hint=f"Use query_job_status to track prompt_id={prompt_id}",
    )
