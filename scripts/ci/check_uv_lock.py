#!/usr/bin/env python3
"""Validate canonical release metadata and installed package versions."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import re
import stat
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli as tomllib


EXPECTED_ROOT_PACKAGE = "dcc-mcp-comfyui"
_PROJECT_VERSION_RE = re.compile(
    r"""
    ^\s*v?
    (?:[0-9]+!)?
    [0-9]+(?:\.[0-9]+)*
    (?:[-_.]?(?:a|b|c|rc|alpha|beta|pre|preview)[-_.]?[0-9]*)?
    (?:(?:-[0-9]+)|(?:[-_.]?(?:post|rev|r)[-_.]?[0-9]*))?
    (?:[-_.]?dev[-_.]?[0-9]*)?
    (?:\+[a-z0-9]+(?:[-_.][a-z0-9]+)*)?
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _load_toml(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _valid_project_version(value: object) -> bool:
    return isinstance(value, str) and _PROJECT_VERSION_RE.fullmatch(value) is not None


def _uv_lock_is_regular_file(path: Path) -> bool:
    try:
        metadata = os.lstat(str(path))
    except OSError:
        return False
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    file_attributes = getattr(metadata, "st_file_attributes", 0)
    return (
        stat.S_ISREG(metadata.st_mode)
        and not stat.S_ISLNK(metadata.st_mode)
        and not bool(file_attributes & reparse_flag)
    )


class _TaggedScalar:
    """Marker view of a TOML scalar, mirroring release-please's TaggedTOMLParser.

    release-please parses TOML with a parser that wraps every non-object scalar as
    ``{start, end, value}``. A jsonpath filter must therefore read ``@.name.value``
    instead of ``@.name``; the bare form compares an object against a string and
    can never match.
    """

    __slots__ = ("start", "end", "value")

    def __init__(self, value: object) -> None:
        self.start = 0
        self.end = 0
        self.value = value

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _TaggedScalar) and self.value == other.value

    def __hash__(self) -> int:
        return hash(self.value)


def _tag_scalars(node: object) -> object:
    """Recursively wrap non-container TOML leaves the way release-please does."""
    if isinstance(node, dict):
        return {key: _tag_scalars(value) for key, value in node.items()}
    if isinstance(node, list):
        return [_tag_scalars(item) for item in node]
    return _TaggedScalar(node)


class _Missing:
    """Sentinel for a dotted path segment that does not resolve."""

    __slots__ = ()


_MISSING = _Missing()


def _resolve_dotted(node: object, dotted: str) -> object:
    """Resolve ``a.b.c`` against the tagged tree, honouring tag objects.

    A tagged scalar exposes only ``start``/``end``/``value``, so ``name`` yields
    the tag object itself while ``name.value`` yields the underlying string. That
    asymmetry is exactly what makes ``.value`` mandatory in release-please
    filter expressions.
    """
    current = node
    for segment in dotted.split("."):
        if isinstance(current, _TaggedScalar):
            if segment == "value":
                current = current.value
                continue
            return _MISSING
        if isinstance(current, dict):
            if segment not in current:
                return _MISSING
            current = current[segment]
            continue
        return _MISSING
    return current


_JSONPATH_RE = re.compile(
    r"\$\.(?P<root>[A-Za-z_][\w-]*)"
    r"\[\?\(@\.(?P<field>[A-Za-z_][\w.-]*)=='(?P<name>[^']*)'\)\]"
    r"(?:\.(?P<tail>[A-Za-z_][\w.]*))?"
)


def _jsonpath_hit_count(lock: dict, expression: str) -> int:
    """Count nodes the release-please jsonpath resolves to inside uv.lock.

    Mirrors the subset of jsonpath-plus semantics release-please relies on for
    extra-files: a root field, one equality filter over an array of tables, and
    an optional trailing field. The document is evaluated through release-please's
    tagged view, where a scalar is a ``{start, end, value}`` marker object, so
    ``@.name.value`` matches while a bare ``@.name`` cannot. Unrecognised
    expressions count as zero hits so the guard never silently passes on a syntax
    it does not understand.
    """
    match = _JSONPATH_RE.fullmatch(expression.strip())
    if match is None:
        return 0

    root_key = match.group("root")
    if not isinstance(lock.get(root_key), list):
        return 0

    tagged = _tag_scalars(lock)
    entries = tagged[root_key]
    field = match.group("field")
    expected_name = match.group("name")
    tail = match.group("tail")

    hits = 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        actual = _resolve_dotted(entry, field)
        if actual is _MISSING or actual != expected_name:
            continue
        if tail is not None and _resolve_dotted(entry, tail) is _MISSING:
            continue
        hits += 1
    return hits


def _uv_lock_extra_file_jsonpath(release_config: dict) -> str | None:
    """Return the jsonpath release-please applies to uv.lock, if registered."""
    packages = release_config.get("packages")
    if not isinstance(packages, dict):
        return None
    configured_root = packages.get(".")
    if not isinstance(configured_root, dict):
        return None
    extra_files = configured_root.get("extra-files")
    if not isinstance(extra_files, list):
        return None
    for entry in extra_files:
        if not isinstance(entry, dict):
            continue
        if entry.get("path") == "uv.lock" and isinstance(entry.get("jsonpath"), str):
            return entry["jsonpath"]
    return None


def check_uv_lock_consistency(root: Path) -> list[str]:
    """Return stable errors for release metadata and editable-root lock drift."""
    config_path = root / "release-please-config.json"
    manifest_path = root / ".release-please-manifest.json"
    pyproject_path = root / "pyproject.toml"
    lock_path = root / "uv.lock"

    if not _uv_lock_is_regular_file(lock_path):
        return ["uv.lock must be a regular file and not a symlink or reparse point"]

    try:
        release_config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return [f"cannot read {config_path.name}: {type(error).__name__}"]
    if not isinstance(release_config, dict):
        return ["release-please-config.json must contain a JSON object"]
    configured_packages = release_config.get("packages")
    if not isinstance(configured_packages, dict):
        return ["release-please-config.json packages must be a mapping"]
    configured_root = configured_packages.get(".")
    if not isinstance(configured_root, dict):
        return ['release-please-config.json packages["."] must be a mapping']
    configured_name = configured_root.get("package-name")
    if configured_name != EXPECTED_ROOT_PACKAGE:
        return [
            f"release-please-config.json root package-name {configured_name!r} "
            f"!= fixed identity {EXPECTED_ROOT_PACKAGE!r}"
        ]

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return [f"cannot read {manifest_path.name}: {type(error).__name__}"]
    if not isinstance(manifest, dict):
        return [".release-please-manifest.json must contain a JSON object"]
    expected_version = manifest.get(".")
    if not _valid_project_version(expected_version):
        return [f".release-please-manifest.json root version {expected_version!r} is not a valid project version"]

    try:
        pyproject = _load_toml(pyproject_path)
    except (OSError, tomllib.TOMLDecodeError) as error:
        return [f"cannot read {pyproject_path.name}: {type(error).__name__}"]
    if not isinstance(pyproject, dict):
        return ["pyproject.toml must contain a mapping"]
    project = pyproject.get("project")
    if not isinstance(project, dict):
        return ["pyproject.toml project must be a mapping"]
    project_name = project.get("name")
    project_version = project.get("version")
    if project_name != EXPECTED_ROOT_PACKAGE:
        return [f"pyproject.toml project.name {project_name!r} != fixed identity {EXPECTED_ROOT_PACKAGE!r}"]
    if not _valid_project_version(project_version):
        return [f"pyproject.toml project.version {project_version!r} is not a valid project version"]
    if project_version != expected_version:
        return [f"pyproject.toml project.version {project_version!r} != expected {expected_version!r}"]

    try:
        lock = _load_toml(lock_path)
    except (OSError, tomllib.TOMLDecodeError) as error:
        return [f"cannot read {lock_path.name}: {type(error).__name__}"]
    if not isinstance(lock, dict):
        return ["uv.lock must contain a mapping"]
    packages = lock.get("package")
    if not isinstance(packages, list):
        return ["uv.lock package must be a list"]
    if not all(isinstance(package, dict) for package in packages):
        return ["uv.lock package entries must be mappings"]
    sources = [package.get("source") for package in packages]
    if not all(source is None or isinstance(source, dict) for source in sources):
        return ["uv.lock package source values must be mappings"]
    editable_roots = [
        package for package in packages if isinstance(package.get("source"), dict) and "editable" in package["source"]
    ]
    if len(editable_roots) != 1:
        return [f"uv.lock must contain exactly one source mapping with an editable key; found {len(editable_roots)}"]

    editable_root = editable_roots[0]
    editable_source = editable_root["source"]
    if editable_source.get("editable") != ".":
        return [f"uv.lock editable root path {editable_source.get('editable')!r} != canonical '.'"]
    lock_name = editable_root.get("name")
    if lock_name != EXPECTED_ROOT_PACKAGE:
        return [f"uv.lock editable root name {lock_name!r} != fixed identity {EXPECTED_ROOT_PACKAGE!r}"]
    lock_version = editable_root.get("version")
    if not _valid_project_version(lock_version):
        return [f"uv.lock editable root version {lock_version!r} is not a valid project version"]
    if lock_version != expected_version:
        return [
            f"uv.lock editable root {EXPECTED_ROOT_PACKAGE} version {lock_version!r} != expected {expected_version!r}"
        ]

    lock_jsonpath = _uv_lock_extra_file_jsonpath(release_config)
    if lock_jsonpath is None:
        # uv.lock is not registered as an extra-file, so there is no jsonpath to
        # validate. Registration coverage is asserted separately by the workflow
        # tests; this guard only polices jsonpaths that release-please would run.
        return []
    hits = _jsonpath_hit_count(lock, lock_jsonpath)
    if hits < 1:
        return [
            f"release-please uv.lock jsonpath {lock_jsonpath!r} matches {hits} package entries; "
            "release-please would warn and silently no-op, leaving uv.lock stale"
        ]
    return []


def check_installed_versions(root: Path, expected_core: str) -> list[str]:
    """Return stable errors for installed packages that drift from CI inputs."""
    errors = check_uv_lock_consistency(root)
    if errors:
        return errors
    if not _valid_project_version(expected_core):
        return [f"EXPECTED_CORE {expected_core!r} is not a valid project version"]

    manifest = json.loads((root / ".release-please-manifest.json").read_text(encoding="utf-8"))
    expected_versions = {
        "dcc-mcp-core": expected_core,
        EXPECTED_ROOT_PACKAGE: manifest["."],
    }
    for package, expected_version in expected_versions.items():
        try:
            installed_version = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            return [f"installed package {package!r} was not found"]
        if installed_version != expected_version:
            return [f"installed {package} version {installed_version!r} != expected {expected_version!r}"]
    return []


def main() -> None:
    """Run repository-root consistency and optional installed-package checks."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--installed",
        action="store_true",
        help="also validate installed Core and adapter versions",
    )
    args = parser.parse_args()

    root = Path.cwd()
    if args.installed:
        errors = check_installed_versions(root, os.environ.get("EXPECTED_CORE", ""))
    else:
        errors = check_uv_lock_consistency(root)
    if errors:
        for error in errors:
            print(f"::error::{error}", file=sys.stderr)
        raise SystemExit(1)
    if args.installed:
        print("Installed Core and adapter versions match canonical release metadata.")
    else:
        print("Release metadata and uv.lock editable root version are consistent.")


if __name__ == "__main__":
    main()
