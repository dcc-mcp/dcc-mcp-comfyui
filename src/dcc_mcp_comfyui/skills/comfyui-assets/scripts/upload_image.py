"""Typed entry point for bounded ComfyUI image upload."""

from dcc_mcp_core.skill import run_main, skill_entry, skill_success

from dcc_mcp_comfyui.skill_runtime import connected_bridge


@skill_entry
def main(
    source: str,
    subfolder: str = "",
    folder_type: str = "input",
    overwrite: bool = False,
    max_file_bytes: int = 536870912,
) -> dict:
    with connected_bridge() as bridge:
        result = bridge.upload_image(
            source,
            subfolder=subfolder,
            folder_type=folder_type,
            overwrite=overwrite,
            max_file_bytes=max_file_bytes,
        )
    return skill_success("Image uploaded to ComfyUI.", **result)


if __name__ == "__main__":
    run_main(main)
