"""Typed entry point for redacted ComfyUI runtime diagnostics."""

from dcc_mcp_core.skill import run_main, skill_entry, skill_success

from dcc_mcp_comfyui.skill_runtime import connected_bridge


@skill_entry
def main() -> dict:
    with connected_bridge() as bridge:
        runtime = bridge.get_runtime_status()
    return skill_success("ComfyUI runtime inspected.", **runtime)


if __name__ == "__main__":
    run_main(main)
