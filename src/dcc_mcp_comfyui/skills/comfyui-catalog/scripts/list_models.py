"""Typed entry point for one ComfyUI model folder."""

from dcc_mcp_core.skill import run_main, skill_entry, skill_success

from dcc_mcp_comfyui.skill_runtime import connected_bridge


@skill_entry
def main(folder: str, limit: int = 1000) -> dict:
    with connected_bridge() as bridge:
        models = bridge.list_models(folder, limit=limit)
    return skill_success("ComfyUI models listed.", folder=folder, models=models, count=len(models))


if __name__ == "__main__":
    run_main(main)
