"""Typed entry point for ComfyUI feature discovery."""

from dcc_mcp_core.skill import run_main, skill_entry, skill_success

from dcc_mcp_comfyui.skill_runtime import connected_bridge


@skill_entry
def main() -> dict:
    with connected_bridge() as bridge:
        features = bridge.get_features()
    return skill_success("ComfyUI features inspected.", features=features)


if __name__ == "__main__":
    run_main(main)
