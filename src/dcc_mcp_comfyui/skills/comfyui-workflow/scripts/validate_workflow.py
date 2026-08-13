"""Typed entry point for ComfyUI workflow validation."""

from __future__ import annotations

from typing import Any

from dcc_mcp_core.skill import run_main, skill_entry, skill_success

from dcc_mcp_comfyui.skill_runtime import connected_bridge


@skill_entry
def main(workflow: dict[str, Any]) -> dict:
    with connected_bridge() as bridge:
        validation = bridge.validate_workflow(workflow)
    state = "passed" if validation["valid"] else "failed"
    return skill_success(f"Workflow validation {state}.", validation=validation)


if __name__ == "__main__":
    run_main(main)
