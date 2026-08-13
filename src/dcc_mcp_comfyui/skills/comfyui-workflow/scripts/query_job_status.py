"""Typed entry point for ComfyUI prompt status inspection."""

from __future__ import annotations

from dcc_mcp_core.skill import run_main, skill_entry, skill_success

from dcc_mcp_comfyui.skill_runtime import connected_bridge


@skill_entry
def main(prompt_id: str) -> dict:
    with connected_bridge() as bridge:
        status = bridge.get_prompt_status(prompt_id)
        artifacts = bridge.list_artifacts(prompt_id) if status["done"] and status["status"] == "completed" else []

    return skill_success(
        f"Prompt status: {status['status']}.",
        prompt_id=prompt_id,
        done=status["done"],
        status=status["status"],
        outputs=status.get("outputs", {}),
        error_message=status.get("error_message"),
        artifacts=artifacts,
    )


if __name__ == "__main__":
    run_main(main)
