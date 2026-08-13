"""Typed entry point for ComfyUI model-folder discovery."""

from dcc_mcp_core.skill import run_main, skill_entry, skill_success

from dcc_mcp_comfyui.skill_runtime import connected_bridge


@skill_entry
def main(limit: int = 1000) -> dict:
    with connected_bridge() as bridge:
        folders = bridge.list_model_folders(limit=limit)
    return skill_success("ComfyUI model folders listed.", folders=folders, count=len(folders))


if __name__ == "__main__":
    run_main(main)
