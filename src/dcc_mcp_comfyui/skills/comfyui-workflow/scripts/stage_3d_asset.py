"""Stage a bounded producer export into ComfyUI's Load3D input area."""

from __future__ import annotations

from pathlib import Path

from _runtime import connected_bridge
from dcc_mcp_core.skill import run_main, skill_entry, skill_success

from dcc_mcp_comfyui._env import (
    resolve_comfyui_input_dir,
    resolve_sync_max_asset_bytes,
    resolve_sync_source_root,
)
from dcc_mcp_comfyui.asset_sync import stage_3d_asset as stage_asset

MIME_BY_FORMAT = {
    "fbx": "application/octet-stream",
    "glb": "model/gltf-binary",
    "gltf": "model/gltf+json",
    "obj": "model/obj",
    "stl": "model/stl",
}


@skill_entry
def main(
    source_name: str,
    channel_id: str,
    asset_id: str,
    format: str,
    expected_head_revision: int = 0,
    source_instance_id: str | None = None,
) -> dict:
    normalized_format = format.strip().lower().lstrip(".")
    result = stage_asset(
        source_name=source_name,
        source_root=Path(resolve_sync_source_root()),
        input_root=Path(resolve_comfyui_input_dir()),
        channel_id=channel_id,
        asset_id=asset_id,
        format=normalized_format,
        mime=MIME_BY_FORMAT.get(normalized_format, "application/octet-stream"),
        expected_head_revision=expected_head_revision,
        source_instance_id=source_instance_id,
        max_asset_bytes=resolve_sync_max_asset_bytes(),
    )

    input_path = Path(result["input_name"])
    with connected_bridge() as bridge:
        result["url"] = bridge.get_artifact_url(
            input_path.name,
            subfolder=input_path.parent.as_posix(),
            folder_type="input",
        )

    return skill_success(
        f"Staged {asset_id} revision {result['revision']['revision']} for ComfyUI Load3D.",
        **result,
    )


if __name__ == "__main__":
    run_main(main)
