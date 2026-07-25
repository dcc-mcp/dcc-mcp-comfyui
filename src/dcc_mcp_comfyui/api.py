"""High-level ComfyUI skill authoring helpers."""

from __future__ import annotations

import functools
import logging
from typing import Any, Callable, Optional, TypeVar

logger = logging.getLogger(__name__)

_F = TypeVar("_F", bound=Callable[..., Any])

_bridge = None


class ComfyUINotAvailableError(RuntimeError):
    """Raised when the ComfyUI bridge is unavailable."""


def set_bridge(bridge: Any) -> None:
    """Set the module-level bridge instance for skill scripts."""
    global _bridge  # noqa: PLW0603
    _bridge = bridge


def get_bridge():
    """Return the ComfyUI bridge instance."""
    if _bridge is None:
        raise ComfyUINotAvailableError("ComfyUI bridge is not available. Start the dcc-mcp-comfyui server first.")
    return _bridge


def is_comfyui_available() -> bool:
    """Return True when the bridge is connected."""
    return _bridge is not None


def cf_success(message: str, *, prompt: Optional[str] = None, **context: Any) -> dict:
    """Build a success envelope for ComfyUI skill results."""
    from dcc_mcp_core.skill import skill_success  # noqa: PLC0415

    return skill_success(message, prompt=prompt, **context)


def cf_error(
    message: str,
    error: str,
    *,
    prompt: Optional[str] = None,
    **context: Any,
) -> dict:
    """Build an error envelope for ComfyUI skill results."""
    from dcc_mcp_core.skill import skill_error  # noqa: PLC0415

    return skill_error(message, error, prompt=prompt, **context)


def cf_from_exception(exc: BaseException, message: Optional[str] = None, **context: Any) -> dict:
    """Build an error envelope from an exception."""
    from dcc_mcp_core.skill import skill_exception  # noqa: PLC0415

    return skill_exception(exc, message=message, **context)


def with_comfyui(func: _F) -> _F:
    """Decorator: standard ComfyUI error handling for skill handlers."""

    @functools.wraps(func)
    def wrapper(**kwargs: Any) -> dict:
        try:
            return func(**kwargs)
        except ComfyUINotAvailableError as exc:
            return cf_error(
                "ComfyUI bridge is not available",
                str(exc),
                prompt="Start ComfyUI and the dcc-mcp-comfyui server.",
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Skill execution failed: %s", func.__name__)
            return cf_from_exception(exc)

    return wrapper  # type: ignore[return-value]
