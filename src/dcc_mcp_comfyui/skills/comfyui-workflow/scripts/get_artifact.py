"""Get the download URL and metadata for a ComfyUI output artifact.

Usage: called as a skill script by dcc-mcp-core with kwargs from tools.yaml.
"""

from __future__ import annotations

from typing import Any

from dcc_mcp_comfyui.api import cf_success, get_bridge, with_comfyui


@with_comfyui
def run(**kwargs: Any) -> dict:
    prompt_id = kwargs.get("prompt_id")
    filename = kwargs.get("filename")
    if not prompt_id or not filename:
        return cf_success(
            "Missing required parameters",
            error="prompt_id and filename are required",
        )

    subfolder = kwargs.get("subfolder", "")
    folder_type = kwargs.get("folder_type", "output")

    bridge = get_bridge()
    url = bridge.get_artifact_url(filename, subfolder=subfolder, folder_type=folder_type)

    return cf_success(
        f"Artifact URL for {filename}",
        prompt_id=prompt_id,
        filename=filename,
        subfolder=subfolder,
        folder_type=folder_type,
        url=url,
    )
