"""Typed entry point for ComfyUI artifact URL construction."""

from __future__ import annotations

from _runtime import connected_bridge
from dcc_mcp_core.skill import run_main, skill_entry, skill_success


@skill_entry
def main(
    prompt_id: str,
    filename: str,
    subfolder: str = "",
    folder_type: str = "output",
) -> dict:
    with connected_bridge() as bridge:
        url = bridge.get_artifact_url(
            filename,
            subfolder=subfolder,
            folder_type=folder_type,
        )

    return skill_success(
        f"Artifact URL prepared for {filename}.",
        prompt_id=prompt_id,
        filename=filename,
        subfolder=subfolder,
        folder_type=folder_type,
        url=url,
    )


if __name__ == "__main__":
    run_main(main)
