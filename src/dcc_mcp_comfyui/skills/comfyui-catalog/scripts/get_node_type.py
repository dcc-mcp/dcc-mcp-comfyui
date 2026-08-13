"""Typed entry point for one exact ComfyUI node contract."""

from dcc_mcp_core.skill import run_main, skill_entry, skill_success

from dcc_mcp_comfyui.skill_runtime import connected_bridge


@skill_entry
def main(node_class: str) -> dict:
    with connected_bridge() as bridge:
        result = bridge.get_node_type(node_class)
    return skill_success("ComfyUI node contract retrieved.", **result)


if __name__ == "__main__":
    run_main(main)
