"""Typed entry point for prompt-owned atomic artifact download."""

from dcc_mcp_core.skill import run_main, skill_entry, skill_success

from dcc_mcp_comfyui.skill_runtime import connected_bridge


@skill_entry
def main(
    prompt_id: str,
    filename: str,
    target: str,
    subfolder: str = "",
    folder_type: str = "output",
    overwrite: bool = False,
    max_file_bytes: int = 536870912,
) -> dict:
    with connected_bridge() as bridge:
        result = bridge.download_artifact(
            prompt_id,
            filename,
            target,
            subfolder=subfolder,
            folder_type=folder_type,
            overwrite=overwrite,
            max_file_bytes=max_file_bytes,
        )
    return skill_success("Prompt-owned artifact downloaded atomically.", **result)


if __name__ == "__main__":
    run_main(main)
