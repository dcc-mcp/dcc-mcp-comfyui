"""Bounded inbound asset synchronization for ComfyUI."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path, PureWindowsPath
from typing import Any

from dcc_mcp_core.asset_sync import AssetSyncValidationError, FileAssetSyncStore

SUPPORTED_3D_FORMATS = frozenset({"fbx", "glb", "gltf", "obj", "stl"})
DEFAULT_MAX_ASSET_BYTES = 256 * 1024 * 1024

__all__ = ["AssetSyncValidationError", "stage_3d_asset"]


def _write_latest_pointer(input_root: Path, *, channel_id: str, asset_id: str, payload: dict[str, Any]) -> Path:
    pointer_dir = input_root / "3d" / ".dcc-mcp-latest" / channel_id
    pointer_dir.mkdir(parents=True, exist_ok=True)
    pointer_path = pointer_dir / f"{asset_id}.json"
    fd, temporary_name = tempfile.mkstemp(prefix=f".{asset_id}.", suffix=".tmp", dir=pointer_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, pointer_path)
    except Exception:
        Path(temporary_name).unlink(missing_ok=True)
        raise
    return pointer_path


def _resolve_source(source_root: Path, source_name: str) -> Path:
    root = source_root.resolve()
    requested_name = str(source_name).strip()
    requested = Path(requested_name)
    if (
        not requested_name
        or bool(requested.anchor)
        or PureWindowsPath(requested_name).is_absolute()
        or any(part in {"", ".", ".."} for part in requested.parts)
    ):
        raise AssetSyncValidationError("source_name must be a safe relative path")
    source = (root / requested).resolve(strict=True)
    try:
        source.relative_to(root)
    except ValueError as exc:
        raise AssetSyncValidationError("source_name escapes the configured source root") from exc
    if not source.is_file():
        raise AssetSyncValidationError("source_name must reference a regular file")
    return source


def stage_3d_asset(
    *,
    source_name: str,
    source_root: Path,
    input_root: Path,
    channel_id: str,
    asset_id: str,
    format: str,
    mime: str,
    expected_head_revision: int,
    source_instance_id: str | None = None,
    max_asset_bytes: int = DEFAULT_MAX_ASSET_BYTES,
) -> dict[str, Any]:
    """Publish and materialize one 3D revision under ``ComfyUI/input/3d``."""
    normalized_format = str(format).strip().lower().lstrip(".")
    if normalized_format not in SUPPORTED_3D_FORMATS:
        supported = ", ".join(sorted(SUPPORTED_3D_FORMATS))
        raise AssetSyncValidationError(f"format must be one of: {supported}")

    source = _resolve_source(Path(source_root), source_name)
    size_bytes = source.stat().st_size
    if size_bytes > max_asset_bytes:
        raise AssetSyncValidationError(f"asset exceeds configured {max_asset_bytes}-byte limit")
    if source.suffix.lower() != f".{normalized_format}":
        raise AssetSyncValidationError("source_name extension does not match format")

    trusted_input_root = Path(input_root).resolve()
    store = FileAssetSyncStore(trusted_input_root / ".dcc-mcp-sync")
    revision = store.publish(
        source,
        channel_id=channel_id,
        asset_id=asset_id,
        format=normalized_format,
        mime=mime,
        expected_head_revision=expected_head_revision,
        source_instance_id=source_instance_id,
    )
    staged = store.materialize(revision, trusted_input_root, subfolder="3d")

    input_name = staged.relative_to(trusted_input_root).as_posix()
    latest = {
        "channel_id": revision.channel_id,
        "asset_id": revision.asset_id,
        "revision": revision.revision,
        "digest": revision.digest,
        "format": revision.format,
        "mime": revision.mime,
        "input_name": input_name,
        "created_at": revision.created_at,
    }
    _write_latest_pointer(
        trusted_input_root,
        channel_id=revision.channel_id,
        asset_id=revision.asset_id,
        payload=latest,
    )

    return {
        "revision": revision.to_dict(),
        "input_name": input_name,
        "latest": latest,
    }
