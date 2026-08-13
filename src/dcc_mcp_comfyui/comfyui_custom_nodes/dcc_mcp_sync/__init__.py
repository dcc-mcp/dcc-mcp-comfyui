"""ComfyUI web bridge for immutable DCC-MCP asset revisions."""

from __future__ import annotations

import json
import re
from pathlib import Path

import folder_paths
from aiohttp import web
from server import PromptServer

_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _validate_identifier(value: str, field: str) -> str:
    normalized = str(value).strip()
    if not _IDENTIFIER_PATTERN.fullmatch(normalized):
        raise web.HTTPBadRequest(text=f"{field} is invalid")
    return normalized


@PromptServer.instance.routes.get("/dcc-mcp-sync/latest")
async def latest_revision(request: web.Request) -> web.Response:
    channel_id = _validate_identifier(request.query.get("channel_id", ""), "channel_id")
    asset_id = _validate_identifier(request.query.get("asset_id", ""), "asset_id")
    input_root = Path(folder_paths.get_input_directory()).resolve()
    pointer_root = (input_root / "3d" / ".dcc-mcp-latest").resolve()
    pointer_path = (pointer_root / channel_id / f"{asset_id}.json").resolve()
    try:
        pointer_path.relative_to(pointer_root)
    except ValueError as exc:
        raise web.HTTPBadRequest(text="asset pointer escapes the input root") from exc
    if not pointer_path.is_file():
        raise web.HTTPNotFound(text="no synchronized revision is available")
    try:
        payload = json.loads(pointer_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise web.HTTPInternalServerError(text="the synchronized revision pointer is unreadable") from exc
    return web.json_response(payload)


WEB_DIRECTORY = "./web"
NODE_CLASS_MAPPINGS: dict[str, object] = {}
NODE_DISPLAY_NAME_MAPPINGS: dict[str, str] = {}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
