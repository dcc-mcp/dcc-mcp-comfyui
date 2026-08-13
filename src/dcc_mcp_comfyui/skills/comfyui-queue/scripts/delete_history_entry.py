"""Typed entry point for exact ComfyUI history deletion."""

from dcc_mcp_core.skill import run_main, skill_entry, skill_success

from dcc_mcp_comfyui.skill_runtime import connected_bridge


@skill_entry
def main(prompt_id: str) -> dict:
    with connected_bridge() as bridge:
        result = bridge.delete_history_entry(prompt_id)
    return skill_success("ComfyUI history entry processed.", **result)


if __name__ == "__main__":
    run_main(main)
