"""Process-local ComfyUI connection helper for Skill subprocesses."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from dcc_mcp_comfyui._env import resolve_comfyui_base_url, resolve_comfyui_timeout
from dcc_mcp_comfyui.bridge import ComfyUIBridge


@contextmanager
def connected_bridge() -> Iterator[ComfyUIBridge]:
    """Create a short-lived bridge using the adapter's public environment contract."""
    bridge = ComfyUIBridge(
        base_url=resolve_comfyui_base_url(),
        timeout=resolve_comfyui_timeout(),
    )
    bridge.connect()
    try:
        yield bridge
    finally:
        bridge.disconnect()
