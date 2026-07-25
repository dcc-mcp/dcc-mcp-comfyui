"""Environment variable helpers for dcc-mcp-comfyui."""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

ENV_PORT = "DCC_MCP_COMFYUI_PORT"
ENV_GATEWAY_PORT = "DCC_MCP_GATEWAY_PORT"
ENV_COMFYUI_BASE_URL = "DCC_MCP_COMFYUI_BASE_URL"
ENV_COMFYUI_TIMEOUT = "DCC_MCP_COMFYUI_TIMEOUT"
ENV_ENABLE_GATEWAY_FAILOVER = "DCC_MCP_COMFYUI_ENABLE_GATEWAY_FAILOVER"

DEFAULT_COMFYUI_BASE_URL = "http://127.0.0.1:8188"
DEFAULT_COMFYUI_TIMEOUT = 120.0


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def resolve_comfyui_base_url(value: Optional[str] = None) -> str:
    """Return the ComfyUI server base URL from arg, env, or default."""
    if value:
        return value.rstrip("/")
    raw = os.environ.get(ENV_COMFYUI_BASE_URL, "").strip()
    if raw:
        return raw.rstrip("/")
    return DEFAULT_COMFYUI_BASE_URL


def resolve_comfyui_timeout(value: Optional[float] = None) -> float:
    """Return the ComfyUI request timeout from arg, env, or default."""
    if value is not None:
        return float(value)
    raw = os.environ.get(ENV_COMFYUI_TIMEOUT, "").strip()
    if raw:
        try:
            return float(raw)
        except ValueError:
            logger.warning("Invalid %s=%r; using default %.1f", ENV_COMFYUI_TIMEOUT, raw, DEFAULT_COMFYUI_TIMEOUT)
    return DEFAULT_COMFYUI_TIMEOUT


def resolve_enable_gateway_failover(value: Optional[bool]) -> bool:
    if value is not None:
        return value
    raw = os.environ.get(ENV_ENABLE_GATEWAY_FAILOVER, "").strip()
    if raw:
        return _env_truthy(ENV_ENABLE_GATEWAY_FAILOVER)
    return True


def resolve_minimal_mode_enabled() -> bool:
    raw = os.environ.get("DCC_MCP_MINIMAL", "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def get_extra_skill_paths() -> list[str]:
    """Read ``DCC_MCP_COMFYUI_SKILL_PATHS`` and ``DCC_MCP_SKILL_PATHS``."""
    sep = ";" if os.sep == "\\" else ":"
    paths: list[str] = []

    for env_var in ("DCC_MCP_COMFYUI_SKILL_PATHS", "DCC_MCP_SKILL_PATHS"):
        raw = os.environ.get(env_var, "")
        if raw:
            for part in raw.split(sep):
                part = part.strip()
                if part:
                    paths.append(part)

    return paths
