"""Typed entry point for bounded ComfyUI memory reclamation."""

from dcc_mcp_core.skill import run_main, skill_entry, skill_success

from dcc_mcp_comfyui.skill_runtime import connected_bridge


@skill_entry
def main(unload_models: bool = False, free_memory: bool = True) -> dict:
    with connected_bridge() as bridge:
        result = bridge.free_memory(unload_models=unload_models, free_memory=free_memory)
    return skill_success("ComfyUI memory action accepted.", **result)


if __name__ == "__main__":
    run_main(main)
