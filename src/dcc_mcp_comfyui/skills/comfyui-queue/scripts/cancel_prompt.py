"""Typed entry point for exact ComfyUI prompt cancellation."""

from dcc_mcp_core.skill import run_main, skill_entry, skill_success

from dcc_mcp_comfyui.skill_runtime import connected_bridge


@skill_entry
def main(prompt_id: str) -> dict:
    with connected_bridge() as bridge:
        result = bridge.cancel_prompt(prompt_id)
    return skill_success(f"ComfyUI cancellation action: {result['action']}.", **result)


if __name__ == "__main__":
    run_main(main)
