"""Typed entry point for ComfyUI workflow submission."""

from __future__ import annotations

from typing import Any

from dcc_mcp_core.skill import run_main, skill_entry, skill_error, skill_success

from dcc_mcp_comfyui.skill_runtime import connected_bridge


@skill_entry
def main(
    workflow: dict[str, Any],
    wait: bool = False,
    timeout: float = 120,
) -> dict:
    with connected_bridge() as bridge:
        validation = bridge.validate_workflow(workflow)
        if not validation["valid"]:
            return skill_error(
                "Workflow validation failed; the prompt was not submitted.",
                "; ".join(validation["errors"]) or "invalid workflow",
                prompt_id=None,
                number=-1,
                node_errors={},
                validation=validation,
            )

        result = bridge.submit_workflow(workflow)
        prompt_id = result["prompt_id"]
        if wait:
            status = bridge.wait_for_prompt(prompt_id, timeout=timeout)
            return skill_success(
                f"Workflow reached terminal state: {status['status']}.",
                prompt_id=prompt_id,
                number=result["number"],
                node_errors=result["node_errors"],
                status=status["status"],
                outputs=status.get("outputs", {}),
                error_message=status.get("error_message"),
            )

    return skill_success(
        "Workflow submitted to the ComfyUI queue.",
        prompt_id=prompt_id,
        number=result["number"],
        node_errors=result["node_errors"],
    )


if __name__ == "__main__":
    run_main(main)
