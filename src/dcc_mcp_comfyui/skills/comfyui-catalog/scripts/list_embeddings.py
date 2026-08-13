"""Typed entry point for ComfyUI embedding discovery."""

from dcc_mcp_core.skill import run_main, skill_entry, skill_success

from dcc_mcp_comfyui.skill_runtime import connected_bridge


@skill_entry
def main(limit: int = 1000) -> dict:
    with connected_bridge() as bridge:
        embeddings = bridge.list_embeddings(limit=limit)
    return skill_success("ComfyUI embeddings listed.", embeddings=embeddings, count=len(embeddings))


if __name__ == "__main__":
    run_main(main)
