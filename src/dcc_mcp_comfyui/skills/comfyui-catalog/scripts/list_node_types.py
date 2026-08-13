"""Typed entry point for bounded ComfyUI node summaries."""

from dcc_mcp_core.skill import run_main, skill_entry, skill_success

from dcc_mcp_comfyui.skill_runtime import connected_bridge


@skill_entry
def main(query: str = "", category: str = "", limit: int = 200) -> dict:
    with connected_bridge() as bridge:
        nodes = bridge.list_node_types(query=query, category=category, limit=limit)
    return skill_success("ComfyUI node types listed.", nodes=nodes, count=len(nodes))


if __name__ == "__main__":
    run_main(main)
