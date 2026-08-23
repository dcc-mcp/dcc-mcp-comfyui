"""Agent-first install and verify lifecycle for ComfyUI."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Optional, Sequence
from urllib.parse import urlsplit

import httpx

from dcc_mcp_comfyui.__version__ import __version__
from dcc_mcp_comfyui._env import (
    DEFAULT_COMFYUI_BASE_URL,
    ENV_COMFYUI_BASE_URL,
    ENV_COMFYUI_INPUT_DIR,
    ENV_SYNC_SOURCE_ROOT,
)

try:  # Core #2252 exports these after the shared SOP foundation lands.
    from dcc_mcp_core.deployment import (
        INSTALL_EXIT_ACQUIRE,
        INSTALL_EXIT_INSTALL,
        INSTALL_EXIT_OK,
        INSTALL_EXIT_PREFLIGHT,
        INSTALL_EXIT_REQUIRES_RESTART,
        INSTALL_EXIT_VERIFY,
    )
except (ImportError, ModuleNotFoundError):  # Thin compatibility with current Core.
    INSTALL_EXIT_OK = 0
    INSTALL_EXIT_PREFLIGHT = 10
    INSTALL_EXIT_ACQUIRE = 20
    INSTALL_EXIT_INSTALL = 30
    INSTALL_EXIT_VERIFY = 40
    INSTALL_EXIT_REQUIRES_RESTART = 50

EXIT_OK = INSTALL_EXIT_OK
EXIT_PREFLIGHT = INSTALL_EXIT_PREFLIGHT
EXIT_ACQUIRE = INSTALL_EXIT_ACQUIRE
EXIT_INSTALL = INSTALL_EXIT_INSTALL
EXIT_VERIFY = INSTALL_EXIT_VERIFY
EXIT_REQUIRES_RESTART = INSTALL_EXIT_REQUIRES_RESTART

SCHEMA_VERSION = 1
DCC_TYPE = "comfyui"
MIN_CORE_VERSION = "0.20.6"
MIN_COMFYUI_VERSION = "0.32.0"
CUSTOM_NODE_NAME = "dcc_mcp_sync"
LIFECYCLE_COMMANDS = frozenset({"doctor", "verify", "install", "status", "uninstall", "upgrade"})
DEFAULT_RECEIPT_PATH = Path.home() / ".dcc-mcp" / "receipts" / "comfyui.json"


class LifecycleError(RuntimeError):
    """A classified lifecycle failure."""

    def __init__(
        self,
        exit_code: int,
        stage: str,
        reason: str,
        message: str,
        *,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.stage = stage
        self.reason = reason
        self.details = details or {}


def load_install_sop_schema() -> dict[str, Any]:
    """Load Core's schema when available, otherwise the packaged compatible copy."""
    try:
        from dcc_mcp_core.deployment import load_install_sop_schema as load_shared
    except (ImportError, ModuleNotFoundError):
        path = Path(__file__).resolve().parent / "schemas" / "adapter-install-sop-v1.schema.json"
        return json.loads(path.read_text(encoding="utf-8"))
    return load_shared()


def _distribution_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def _receipt_path(value: Optional[Path]) -> Path:
    configured = value or Path(os.environ.get("DCC_MCP_COMFYUI_RECEIPT", DEFAULT_RECEIPT_PATH))
    return configured.expanduser().resolve()


def _base_report(command: str, receipt_path: Path) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "running",
        "dcc_type": DCC_TYPE,
        "command": command,
        "adapter_version": __version__,
        "core_version": _distribution_version("dcc-mcp-core"),
        "min_core_version": MIN_CORE_VERSION,
        "min_comfyui_version": MIN_COMFYUI_VERSION,
        "steps": [],
        "next_steps": [],
        "receipt_path": str(receipt_path),
        "verify": {
            "directly_usable": False,
            "failure_stage": None,
            "failure_reason": None,
        },
        "directly_usable": False,
        "failure_stage": None,
        "failure_reason": None,
        "requires_restart": False,
    }


def _set_failure(
    report: dict[str, Any],
    *,
    stage: str,
    reason: str,
    message: str,
    status: str = "failed",
    details: Optional[dict[str, Any]] = None,
) -> None:
    report.update(
        {
            "status": status,
            "failure_stage": stage,
            "failure_reason": reason,
            "message": message,
        }
    )
    report["verify"].update({"directly_usable": False, "failure_stage": stage, "failure_reason": reason})
    if details:
        report["details"] = details


def _next_step(
    step_id: str,
    description: str,
    why: str,
    command: Sequence[str],
    **extra: Any,
) -> dict[str, Any]:
    return {
        "id": step_id,
        "description": description,
        "why": why,
        "command": [str(item) for item in command],
        **extra,
    }


def _command_for(args: argparse.Namespace, command: str, *, execute: bool = False) -> list[str]:
    result = ["dcc-mcp-comfyui", command, "--json"]
    if execute:
        result.append("--yes")
    for flag, value in (
        ("--comfyui-base-url", args.comfyui_base_url),
        ("--dcc-path", args.dcc_path),
        ("--python", args.python),
        ("--receipt-path", args.receipt_path),
        ("--sync-source-root", args.sync_source_root),
        ("--input-dir", args.input_dir),
    ):
        if value:
            result.extend([flag, str(value)])
    return result


def _install_next_step(args: argparse.Namespace, *, missing_path: bool) -> dict[str, Any]:
    command = _command_for(args, "install")
    if missing_path:
        command.extend(["--dcc-path", "<COMFYUI_ROOT_CONTAINING_MAIN_PY>"])
    return _next_step(
        "install-custom-node",
        "Install the bundled dcc_mcp_sync custom node into the exact ComfyUI root.",
        "Load3D synchronization requires files under ComfyUI/custom_nodes and cannot be enabled by HTTP alone.",
        command,
    )


def _restart_verify_next_step(args: argparse.Namespace) -> dict[str, Any]:
    return _next_step(
        "restart-comfyui-and-verify",
        "Restart ComfyUI and repeat typed synchronization verification.",
        "ComfyUI discovers custom nodes and their web routes only during startup.",
        _command_for(args, "verify"),
        host="ComfyUI",
        action="Restart the same ComfyUI instance, then run command.",
    )


def _emit(args: argparse.Namespace, report: dict[str, Any], exit_code: int) -> int:
    report["exit_code"] = exit_code
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"{report['command']}: {report['status']}")
        if report.get("message"):
            print(report["message"])
        for next_step in report["next_steps"]:
            print("Next:", " ".join(next_step["command"]))
    return exit_code


def _version_tuple(value: str) -> Optional[tuple[int, int, int]]:
    match = re.search(r"(?<!\d)(\d+)\.(\d+)(?:\.(\d+))?", str(value))
    if not match:
        return None
    return tuple(int(part or 0) for part in match.groups())


def _version_at_least(value: str, floor: str) -> bool:
    parsed = _version_tuple(value)
    required = _version_tuple(floor)
    return parsed is not None and required is not None and parsed >= required


def _normalize_base_url(value: Optional[str]) -> tuple[str, str]:
    explicit = str(value or "").strip()
    configured = explicit or os.environ.get(ENV_COMFYUI_BASE_URL, "").strip()
    source = "argument" if explicit else ("environment" if configured else "default")
    url = (configured or DEFAULT_COMFYUI_BASE_URL).rstrip("/")
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise LifecycleError(
            EXIT_PREFLIGHT,
            "preflight",
            "base_url_invalid",
            "ComfyUI base URL must be one credential-free http(s) origin.",
        )
    return url, source


_PYTHON_PROBE = """
import importlib.metadata
import json
import sys
import dcc_mcp_comfyui
import dcc_mcp_core
print(json.dumps({
    "adapter_version": importlib.metadata.version("dcc-mcp-comfyui"),
    "core_version": importlib.metadata.version("dcc-mcp-core"),
    "python": sys.executable,
    "python_version": sys.version.split()[0],
}))
"""


def _probe_python(python: Path) -> dict[str, Any]:
    if not python.is_file():
        raise LifecycleError(
            EXIT_PREFLIGHT,
            "preflight",
            "python_missing",
            f"Target interpreter does not exist: {python}",
        )
    try:
        completed = subprocess.run(
            [str(python), "-c", _PYTHON_PROBE],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LifecycleError(
            EXIT_PREFLIGHT,
            "preflight",
            "python_probe_failed",
            f"Could not run target Python: {exc}",
        ) from exc
    if completed.returncode != 0:
        diagnostic = (completed.stderr or completed.stdout).strip()[-2000:]
        raise LifecycleError(
            EXIT_PREFLIGHT,
            "preflight",
            "target_import_failed",
            f"Target Python cannot import the adapter and Core: {diagnostic}",
        )
    try:
        result = json.loads(completed.stdout.strip().splitlines()[-1])
    except (IndexError, ValueError) as exc:
        raise LifecycleError(
            EXIT_PREFLIGHT,
            "preflight",
            "python_probe_invalid",
            "Target Python returned invalid probe data.",
        ) from exc
    if not _version_at_least(str(result.get("core_version", "")), MIN_CORE_VERSION):
        raise LifecycleError(
            EXIT_PREFLIGHT,
            "preflight",
            "core_version_unsupported",
            f"dcc-mcp-core {MIN_CORE_VERSION}+ is required; target has {result.get('core_version')}.",
        )
    return result


def _resolve_sync_config(args: argparse.Namespace) -> dict[str, Any]:
    source_value = args.sync_source_root or os.environ.get(ENV_SYNC_SOURCE_ROOT)
    input_value = args.input_dir or os.environ.get(ENV_COMFYUI_INPUT_DIR)
    missing = []
    if not source_value:
        missing.append(ENV_SYNC_SOURCE_ROOT)
    if not input_value:
        missing.append(ENV_COMFYUI_INPUT_DIR)
    if missing:
        raise LifecycleError(
            EXIT_PREFLIGHT,
            "preflight",
            "sync_config_missing",
            f"Required asset-sync configuration is missing: {', '.join(missing)}.",
        )
    source_root = Path(source_value).expanduser().resolve()
    input_root = Path(input_value).expanduser().resolve()
    for name, path in (("sync_source_root", source_root), ("input_dir", input_root)):
        if not path.is_dir():
            raise LifecycleError(
                EXIT_PREFLIGHT,
                "preflight",
                f"{name}_missing",
                f"Configured {name} does not exist: {path}",
            )
    return {
        "sync_source_root_configured": True,
        "input_dir_configured": True,
        "source": {
            "sync_source_root": "argument" if args.sync_source_root else "environment",
            "input_dir": "argument" if args.input_dir else "environment",
        },
    }


def _probe_endpoint(base_url: str, timeout: float) -> dict[str, Any]:
    result: dict[str, Any] = {
        "base_url": base_url,
        "http_ready": False,
        "load3d_ready": False,
        "extension_ready": False,
        "sync_route_ready": False,
        "sync_node_ready": False,
        "comfyui_version": None,
        "min_comfyui_version": MIN_COMFYUI_VERSION,
    }
    try:
        with httpx.Client(timeout=min(max(float(timeout), 0.1), 15.0)) as client:
            stats = client.get(f"{base_url}/system_stats")
            if not stats.is_success:
                result["failure_reason"] = "endpoint_http_error"
                result["http_status"] = stats.status_code
                return result
            payload = stats.json()
            if not isinstance(payload, dict) or not isinstance(payload.get("system"), dict):
                result["failure_reason"] = "system_stats_invalid"
                return result
            result["http_ready"] = True
            version = str(payload["system"].get("comfyui_version") or "")
            result["comfyui_version"] = version or None
            if not _version_at_least(version, MIN_COMFYUI_VERSION):
                result["failure_reason"] = "comfyui_version_unsupported"
                return result

            load3d = client.get(f"{base_url}/object_info/Load3D")
            if load3d.is_success:
                load3d_payload = load3d.json()
                result["load3d_ready"] = isinstance(load3d_payload, dict) and isinstance(
                    load3d_payload.get("Load3D"), dict
                )

            extension = client.get(f"{base_url}/extensions/dcc_mcp_sync/dcc_mcp_sync.js")
            result["extension_ready"] = extension.is_success and ("dcc-mcp-sync/latest" in extension.text)

            route = client.get(
                f"{base_url}/dcc-mcp-sync/latest",
                params={"channel_id": "dcc-mcp-doctor", "asset_id": "probe"},
            )
            result["sync_route_ready"] = route.status_code == 404 and (
                "no synchronized revision is available" in route.text
            )
    except (httpx.HTTPError, OSError, ValueError, json.JSONDecodeError) as exc:
        result["failure_reason"] = "endpoint_unreachable"
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result
    result["sync_node_ready"] = all(result[key] for key in ("load3d_ready", "extension_ready", "sync_route_ready"))
    if not result["load3d_ready"]:
        result["failure_reason"] = "load3d_unavailable"
    elif not result["sync_node_ready"]:
        result["failure_reason"] = "custom_node_runtime_missing"
    return result


def _read_receipt(path: Path, *, required: bool = False) -> Optional[dict[str, Any]]:
    if not path.is_file():
        if required:
            raise LifecycleError(
                EXIT_PREFLIGHT,
                "preflight",
                "receipt_missing",
                f"No ComfyUI custom-node receipt exists at {path}.",
            )
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LifecycleError(
            EXIT_PREFLIGHT,
            "preflight",
            "receipt_invalid",
            f"The ComfyUI custom-node receipt is unreadable: {exc}",
        ) from exc
    if not isinstance(value, dict) or value.get("receipt_version") != 1:
        raise LifecycleError(
            EXIT_PREFLIGHT,
            "preflight",
            "receipt_invalid",
            "The ComfyUI custom-node receipt has an unsupported schema.",
        )
    if value.get("dcc_type") != DCC_TYPE:
        raise LifecycleError(
            EXIT_PREFLIGHT,
            "preflight",
            "receipt_wrong_adapter",
            "The receipt does not belong to the ComfyUI adapter.",
        )
    root_text = str(value.get("comfyui_root") or "")
    target_text = str(value.get("target_path") or "")
    root = Path(root_text).expanduser().resolve()
    target = Path(target_text).expanduser().resolve()
    expected = root / "custom_nodes" / CUSTOM_NODE_NAME
    if not root_text or not target_text or target != expected:
        raise LifecycleError(
            EXIT_PREFLIGHT,
            "preflight",
            "receipt_unsafe_target",
            "The receipt target is not the exact bundled node under its recorded ComfyUI root.",
        )
    return value


def _resolve_comfyui_root(args: argparse.Namespace, receipt: Optional[dict[str, Any]]) -> Optional[Path]:
    value: Any = args.dcc_path or (receipt or {}).get("comfyui_root")
    value = value or os.environ.get("DCC_MCP_COMFYUI_DCC_PATH")
    value = value or os.environ.get("COMFYUI_PATH")
    if not value:
        return None
    candidate = Path(str(value)).expanduser().resolve()
    if candidate.is_file() and candidate.name.lower() == "main.py":
        candidate = candidate.parent
    if (candidate / "main.py").is_file() and (candidate / "custom_nodes").is_dir():
        return candidate
    portable = candidate / "ComfyUI"
    if (portable / "main.py").is_file() and (portable / "custom_nodes").is_dir():
        return portable.resolve()
    raise LifecycleError(
        EXIT_PREFLIGHT,
        "preflight",
        "comfyui_root_invalid",
        "--dcc-path must identify a ComfyUI root containing main.py and custom_nodes.",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _manifest(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        if path.is_symlink():
            raise OSError(f"symlinks are not allowed in an owned payload: {path}")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = _sha256(path)
    return result


def _validate_manifest(receipt: dict[str, Any], target: Path) -> Optional[dict[str, str]]:
    files = receipt.get("files")
    if not isinstance(files, dict) or not files:
        return {"reason": "receipt_manifest_missing", "path": str(target)}
    if not target.is_dir() or target.is_symlink():
        return {"reason": "custom_node_missing", "path": str(target)}
    actual: dict[str, str] = {}
    for path in sorted(target.rglob("*")):
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        if path.is_symlink():
            return {"reason": "installed_symlink_unsafe", "path": str(path)}
        if path.is_file():
            resolved = path.resolve()
            try:
                resolved.relative_to(target)
            except ValueError:
                return {"reason": "installed_file_unsafe", "path": str(resolved)}
            actual[path.relative_to(target).as_posix()] = _sha256(path)
    if set(actual) != set(files):
        return {"reason": "installed_file_set_mismatch", "path": str(target)}
    for relative, digest in files.items():
        if not isinstance(relative, str) or not isinstance(digest, str):
            return {"reason": "receipt_manifest_invalid", "path": str(target)}
        path = (target / relative).resolve()
        try:
            path.relative_to(target)
        except ValueError:
            return {"reason": "receipt_manifest_unsafe", "path": str(path)}
        if actual.get(relative) != digest:
            return {"reason": "installed_file_digest_mismatch", "path": str(path)}
    return None


def _replace_path(source: Path, destination: Path) -> None:
    os.replace(source, destination)


def _is_windows_lock(exc: OSError) -> bool:
    return os.name == "nt" and (isinstance(exc, PermissionError) or getattr(exc, "winerror", None) in {5, 32, 33})


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _rollback_install(
    target: Path,
    target_backup: Path,
    receipt_path: Path,
    receipt_backup: Path,
    *,
    target_committed: bool,
    receipt_committed: bool,
) -> list[str]:
    failures: list[str] = []
    try:
        if target_committed and target.exists():
            shutil.rmtree(target)
        if target_backup.exists():
            _replace_path(target_backup, target)
    except OSError as exc:
        failures.append(f"target: {exc}")
    try:
        if receipt_committed and receipt_path.exists():
            receipt_path.unlink()
        if receipt_backup.exists():
            _replace_path(receipt_backup, receipt_path)
    except OSError as exc:
        failures.append(f"receipt: {exc}")
    return failures


def _install_transaction(
    root: Path, receipt_path: Path, receipt_values: dict[str, Any]
) -> tuple[Path, list[dict[str, str]]]:
    source = Path(__file__).resolve().parent / "comfyui_custom_nodes" / CUSTOM_NODE_NAME
    target = root / "custom_nodes" / CUSTOM_NODE_NAME
    token = uuid.uuid4().hex
    stage = target.parent / f".{CUSTOM_NODE_NAME}.stage-{token}"
    target_backup = target.parent / f".{CUSTOM_NODE_NAME}.backup-{token}"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_stage = receipt_path.with_name(f".{receipt_path.name}.stage-{token}")
    receipt_backup = receipt_path.with_name(f".{receipt_path.name}.backup-{token}")
    target_committed = False
    receipt_committed = False
    try:
        shutil.copytree(source, stage, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        if not (stage / "__init__.py").is_file() or not (stage / "web" / "dcc_mcp_sync.js").is_file():
            raise OSError("the staged dcc_mcp_sync node is incomplete")
        receipt_values["files"] = _manifest(stage)
        _write_json(receipt_stage, receipt_values)
    except OSError as exc:
        shutil.rmtree(stage, ignore_errors=True)
        receipt_stage.unlink(missing_ok=True)
        raise LifecycleError(
            EXIT_INSTALL,
            "install",
            "stage_failed",
            f"Could not stage the custom node and receipt: {exc}",
        ) from exc
    try:
        if target.exists():
            _replace_path(target, target_backup)
        _replace_path(stage, target)
        target_committed = True
        if receipt_path.exists():
            _replace_path(receipt_path, receipt_backup)
        _replace_path(receipt_stage, receipt_path)
        receipt_committed = True
    except OSError as exc:
        rollback_errors = _rollback_install(
            target,
            target_backup,
            receipt_path,
            receipt_backup,
            target_committed=target_committed,
            receipt_committed=receipt_committed,
        )
        shutil.rmtree(stage, ignore_errors=True)
        receipt_stage.unlink(missing_ok=True)
        if rollback_errors:
            raise LifecycleError(
                EXIT_INSTALL,
                "rollback",
                "rollback_failed",
                "Install commit failed and the previous state could not be fully restored.",
                details={"commit_error": str(exc), "rollback_errors": rollback_errors},
            ) from exc
        code = EXIT_REQUIRES_RESTART if _is_windows_lock(exc) else EXIT_INSTALL
        raise LifecycleError(
            code,
            "install",
            "windows_file_lock" if code == EXIT_REQUIRES_RESTART else "commit_failed",
            f"Install commit failed; the previous state was restored: {exc}",
        ) from exc
    cleanup: list[dict[str, str]] = []
    for path, remove in (
        (target_backup, lambda: shutil.rmtree(target_backup)),
        (receipt_backup, receipt_backup.unlink),
    ):
        if not path.exists():
            continue
        try:
            remove()
        except OSError as exc:
            cleanup.append(
                {
                    "path": str(path),
                    "reason": "windows_file_lock" if _is_windows_lock(exc) else "cleanup_failed",
                    "message": str(exc),
                }
            )
    return target, cleanup


def _install_state(receipt: Optional[dict[str, Any]], root: Optional[Path]) -> str:
    if root is None:
        return "fresh" if receipt is None else "partial"
    target = root / "custom_nodes" / CUSTOM_NODE_NAME
    if receipt is None:
        return "partial" if target.exists() else "fresh"
    if not target.is_dir() or _validate_manifest(receipt, target):
        return "partial"
    return "upgrade" if receipt.get("adapter_version") != __version__ else "installed"


def _execute_next_step(args: argparse.Namespace) -> dict[str, Any]:
    return _next_step(
        f"execute-{args.command}",
        f"Execute the validated {args.command} plan.",
        "Lifecycle mutations require explicit confirmation.",
        _command_for(args, args.command, execute=True),
    )


def _without_option(command: list[str], flag: str) -> list[str]:
    result = list(command)
    if flag in result:
        index = result.index(flag)
        del result[index : index + 2]
    return result


def _preflight_recovery_step(args: argparse.Namespace, command_name: str, reason: str) -> dict[str, Any]:
    command = _command_for(args, command_name)
    if reason == "sync_config_missing":
        if not args.sync_source_root:
            command.extend(["--sync-source-root", "<TRUSTED_EXPORT_ROOT>"])
        if not args.input_dir:
            command.extend(["--input-dir", "<COMFYUI_INPUT_ROOT>"])
        return _next_step(
            "configure-sync-roots",
            "Provide both existing bounded asset-sync roots and repeat the check.",
            "The adapter never guesses or creates operator-owned roots during doctor.",
            command,
        )
    if reason == "base_url_invalid":
        command = _without_option(command, "--comfyui-base-url")
        command.extend(["--comfyui-base-url", "<COMFYUI_HTTP_ORIGIN>"])
        return _next_step(
            "set-comfyui-origin",
            "Provide one credential-free ComfyUI HTTP(S) origin.",
            "Paths, credentials, queries, and fragments are not endpoint origins.",
            command,
        )
    if reason in {
        "python_missing",
        "python_probe_failed",
        "python_probe_invalid",
        "target_import_failed",
        "core_version_unsupported",
    }:
        python = str(args.python or sys.executable)
        return _next_step(
            "repair-python-environment",
            "Install the adapter and supported Core into the selected interpreter.",
            "Doctor imports both packages from that exact interpreter.",
            [
                python,
                "-m",
                "pip",
                "install",
                "--upgrade",
                "dcc-mcp-comfyui",
                f"dcc-mcp-core>={MIN_CORE_VERSION},<1",
            ],
        )
    return _next_step(
        "repeat-verification",
        "Repeat typed verification after correcting the reported prerequisite.",
        "The same bounded command confirms whether the correction took effect.",
        command,
    )


def _run_install(args: argparse.Namespace, *, upgrade: bool) -> int:
    receipt_path = _receipt_path(args.receipt_path)
    report = _base_report(args.command, receipt_path)
    try:
        receipt = _read_receipt(receipt_path)
        if upgrade and receipt is None:
            raise LifecycleError(
                EXIT_PREFLIGHT,
                "preflight",
                "receipt_missing",
                "Upgrade requires an existing receipt; use install for a fresh state.",
            )
        root = _resolve_comfyui_root(args, receipt)
        if root is None:
            _set_failure(
                report,
                stage="preflight",
                reason="comfyui_root_required",
                message="Pass the exact ComfyUI root with --dcc-path.",
            )
            report["next_steps"] = [_install_next_step(args, missing_path=True)]
            return _emit(args, report, EXIT_PREFLIGHT)
        if receipt and Path(receipt["comfyui_root"]).resolve() != root:
            raise LifecycleError(
                EXIT_PREFLIGHT,
                "preflight",
                "comfyui_root_mismatch",
                "--dcc-path does not match the existing receipt.",
            )
        python = Path(args.python or (receipt or {}).get("python") or sys.executable).resolve()
        python_probe = _probe_python(python)
        target = root / "custom_nodes" / CUSTOM_NODE_NAME
        state = _install_state(receipt, root)
        if state == "partial" and target.exists():
            reason = "unreceipted_custom_node" if receipt is None else "custom_node_modified"
            raise LifecycleError(
                EXIT_PREFLIGHT,
                "preflight",
                reason,
                "The target contains files that the receipt cannot safely replace.",
            )
        plan_type = (
            "upgrade" if upgrade or state == "upgrade" else ("repair" if state in {"partial", "installed"} else "fresh")
        )
        report.update(
            {
                "core_version": python_probe["core_version"],
                "python": python_probe["python"],
                "comfyui_root": str(root),
                "target_path": str(target),
                "install_state": state,
                "plan_type": plan_type,
            }
        )
        report["steps"] = [
            {"id": "preflight", "status": "ok"},
            {"id": "stage", "status": "planned"},
            {"id": "commit", "status": "planned"},
            {"id": "restart-and-verify", "status": "planned"},
        ]
        if args.dry_run or not args.yes:
            report["status"] = "planned"
            report["next_steps"] = [_execute_next_step(args)]
            return _emit(args, report, EXIT_OK)
        receipt_values = {
            "receipt_version": 1,
            "dcc_type": DCC_TYPE,
            "adapter_version": python_probe["adapter_version"],
            "core_version": python_probe["core_version"],
            "python": str(python),
            "comfyui_root": str(root),
            "target_path": str(target),
        }
        installed, cleanup = _install_transaction(root, receipt_path, receipt_values)
        report["steps"][1]["status"] = "ok"
        report["steps"][2]["status"] = "ok"
        report["target_path"] = str(installed)
        if cleanup:
            locked = any(item["reason"] == "windows_file_lock" for item in cleanup)
            _set_failure(
                report,
                stage="install",
                reason="windows_file_lock" if locked else "previous_state_cleanup_failed",
                message="The new custom node is committed, but generated backup cleanup failed.",
                status="requires_restart" if locked else "partial",
                details={"pending_cleanup": cleanup},
            )
            report["requires_restart"] = locked
            return _emit(args, report, EXIT_REQUIRES_RESTART if locked else EXIT_INSTALL)
        report["steps"][3]["status"] = "required"
        _set_failure(
            report,
            stage="readiness",
            reason="restart_required",
            message="The custom node is installed; restart ComfyUI before typed verification.",
            status="requires_restart",
        )
        report["requires_restart"] = True
        report["next_steps"] = [_restart_verify_next_step(args)]
        return _emit(args, report, EXIT_REQUIRES_RESTART)
    except LifecycleError as exc:
        status = "requires_restart" if exc.exit_code == EXIT_REQUIRES_RESTART else "failed"
        _set_failure(
            report,
            stage=exc.stage,
            reason=exc.reason,
            message=str(exc),
            status=status,
            details=exc.details,
        )
        report["requires_restart"] = exc.exit_code == EXIT_REQUIRES_RESTART
        return _emit(args, report, exc.exit_code)


def _run_status(args: argparse.Namespace) -> int:
    receipt_path = _receipt_path(args.receipt_path)
    report = _base_report(args.command, receipt_path)
    try:
        receipt = _read_receipt(receipt_path)
        root = _resolve_comfyui_root(args, receipt)
        state = _install_state(receipt, root)
        report.update(
            {
                "status": "ok" if state != "partial" else "partial",
                "install_state": state,
                "comfyui_root": str(root) if root else None,
            }
        )
        report["steps"] = [{"id": "inspect", "status": report["status"]}]
        if state == "partial":
            _set_failure(
                report,
                stage="preflight",
                reason="partial_install",
                message="Custom-node files and receipt do not describe one complete owned state.",
                status="partial",
            )
            return _emit(args, report, EXIT_PREFLIGHT)
        return _emit(args, report, EXIT_OK)
    except LifecycleError as exc:
        _set_failure(report, stage=exc.stage, reason=exc.reason, message=str(exc))
        return _emit(args, report, exc.exit_code)


def _run_uninstall(args: argparse.Namespace) -> int:
    receipt_path = _receipt_path(args.receipt_path)
    report = _base_report(args.command, receipt_path)
    try:
        receipt = _read_receipt(receipt_path)
        root = _resolve_comfyui_root(args, receipt)
        if receipt is None:
            target = root / "custom_nodes" / CUSTOM_NODE_NAME if root else None
            if target is not None and target.exists():
                raise LifecycleError(
                    EXIT_PREFLIGHT,
                    "preflight",
                    "unreceipted_custom_node",
                    "Uninstall refuses to remove an unreceipted custom-node directory.",
                )
            report.update({"status": "ok", "install_state": "fresh"})
            report["steps"] = [{"id": "uninstall", "status": "skipped"}]
            return _emit(args, report, EXIT_OK)
        assert root is not None
        receipt_root = Path(receipt["comfyui_root"]).resolve()
        if root != receipt_root:
            raise LifecycleError(
                EXIT_PREFLIGHT,
                "preflight",
                "comfyui_root_mismatch",
                "--dcc-path does not match the receipt.",
            )
        target = Path(receipt["target_path"]).resolve()
        manifest_failure = _validate_manifest(receipt, target)
        if manifest_failure:
            raise LifecycleError(
                EXIT_PREFLIGHT,
                "preflight",
                manifest_failure["reason"],
                "The receipted custom node changed; uninstall will not delete ambiguous files.",
                details=manifest_failure,
            )
        report.update({"comfyui_root": str(root), "target_path": str(target), "install_state": "installed"})
        report["steps"] = [
            {"id": "receipt", "status": "ok"},
            {"id": "remove", "status": "planned"},
        ]
        if args.dry_run or not args.yes:
            report["status"] = "planned"
            report["next_steps"] = [_execute_next_step(args)]
            return _emit(args, report, EXIT_OK)
        token = uuid.uuid4().hex
        tombstone = target.parent / f".{CUSTOM_NODE_NAME}.uninstall-{token}"
        restore_copy = target.parent / f".{CUSTOM_NODE_NAME}.restore-{token}"
        receipt_backup = receipt_path.with_name(f".{receipt_path.name}.uninstall-{token}")
        try:
            shutil.copytree(target, restore_copy)
        except OSError as exc:
            shutil.rmtree(restore_copy, ignore_errors=True)
            raise LifecycleError(
                EXIT_INSTALL,
                "uninstall",
                "uninstall_stage_failed",
                f"Could not stage an uninstall rollback copy: {exc}",
            ) from exc
        target_moved = False
        receipt_moved = False
        try:
            _replace_path(target, tombstone)
            target_moved = True
            _replace_path(receipt_path, receipt_backup)
            receipt_moved = True
            shutil.rmtree(tombstone)
        except OSError as exc:
            rollback_errors: list[str] = []
            try:
                if target_moved:
                    shutil.rmtree(tombstone, ignore_errors=True)
                    if target.exists():
                        shutil.rmtree(target)
                    _replace_path(restore_copy, target)
                elif restore_copy.exists():
                    shutil.rmtree(restore_copy)
            except OSError as rollback_exc:
                rollback_errors.append(f"target: {rollback_exc}")
            try:
                if receipt_moved and receipt_backup.exists() and not receipt_path.exists():
                    _replace_path(receipt_backup, receipt_path)
            except OSError as rollback_exc:
                rollback_errors.append(f"receipt: {rollback_exc}")
            if rollback_errors:
                raise LifecycleError(
                    EXIT_INSTALL,
                    "rollback",
                    "rollback_failed",
                    "Uninstall failed and the receipted state could not be restored.",
                    details={"error": str(exc), "rollback_errors": rollback_errors},
                ) from exc
            code = EXIT_REQUIRES_RESTART if _is_windows_lock(exc) else EXIT_INSTALL
            raise LifecycleError(
                code,
                "uninstall",
                "windows_file_lock" if code == EXIT_REQUIRES_RESTART else "uninstall_failed",
                f"Uninstall failed; the receipted state was restored: {exc}",
            ) from exc
        cleanup: list[dict[str, str]] = []
        for path, remove in (
            (restore_copy, lambda: shutil.rmtree(restore_copy)),
            (receipt_backup, receipt_backup.unlink),
        ):
            try:
                remove()
            except OSError as exc:
                cleanup.append({"path": str(path), "reason": "cleanup_failed", "message": str(exc)})
        if cleanup:
            _set_failure(
                report,
                stage="uninstall",
                reason="uninstall_cleanup_failed",
                message="The custom node was removed, but generated rollback files remain.",
                status="partial",
                details={"pending_cleanup": cleanup},
            )
            report["install_state"] = "fresh"
            return _emit(args, report, EXIT_INSTALL)
        report["steps"][1]["status"] = "ok"
        report.update({"status": "ok", "install_state": "fresh"})
        return _emit(args, report, EXIT_OK)
    except LifecycleError as exc:
        status = "requires_restart" if exc.exit_code == EXIT_REQUIRES_RESTART else "failed"
        _set_failure(
            report,
            stage=exc.stage,
            reason=exc.reason,
            message=str(exc),
            status=status,
            details=exc.details,
        )
        report["requires_restart"] = exc.exit_code == EXIT_REQUIRES_RESTART
        return _emit(args, report, exc.exit_code)


def _run_doctor(args: argparse.Namespace, command: str) -> int:
    receipt_path = _receipt_path(args.receipt_path)
    report = _base_report(command, receipt_path)
    try:
        receipt = _read_receipt(receipt_path)
        root = _resolve_comfyui_root(args, receipt)
        install_state = _install_state(receipt, root)
        base_url, base_url_source = _normalize_base_url(args.comfyui_base_url)
        python_probe = _probe_python(Path(args.python or sys.executable).resolve())
        sync_config = _resolve_sync_config(args)
        report.update(
            {
                "adapter_version": python_probe["adapter_version"],
                "core_version": python_probe["core_version"],
                "python": python_probe["python"],
                "runtime": {
                    "python_executable": python_probe["python"],
                    "python_version": python_probe.get("python_version", "unknown"),
                },
                "endpoint": {"base_url": base_url, "source": base_url_source},
                "config": sync_config,
                "install_state": install_state,
                "comfyui_root": str(root) if root else None,
            }
        )
        if receipt is not None and install_state == "partial":
            target = Path(receipt["target_path"]).resolve()
            manifest_failure = _validate_manifest(receipt, target) or {
                "reason": "partial_install",
                "path": str(target),
            }
            report["steps"].extend(
                [
                    {"id": "python-import", "status": "passed"},
                    {"id": "sync-config", "status": "passed"},
                    {"id": "receipt-ownership", "status": "failed"},
                ]
            )
            _set_failure(
                report,
                stage="verify",
                reason=manifest_failure["reason"],
                message="The custom-node files no longer match their receipt.",
                details=manifest_failure,
            )
            report["next_steps"] = [
                _next_step(
                    "inspect-install-state",
                    "Inspect the owned custom-node state before any mutation.",
                    "Verify refuses to hide missing, modified, or additional files.",
                    _command_for(args, "status"),
                )
            ]
            return _emit(args, report, EXIT_VERIFY)
        connectivity = _probe_endpoint(base_url, args.comfyui_timeout)
        report["connectivity"] = connectivity
        report["steps"].extend(
            [
                {"id": "python-import", "status": "passed"},
                {"id": "sync-config", "status": "passed"},
                {
                    "id": "typed-connectivity",
                    "status": "passed" if connectivity["sync_node_ready"] else "failed",
                },
            ]
        )
        if not connectivity["sync_node_ready"]:
            reason = str(connectivity.get("failure_reason") or "endpoint_unusable")
            _set_failure(
                report,
                stage="verify",
                reason=reason,
                message=(
                    "ComfyUI is reachable, but the typed Load3D synchronization contract is not usable."
                    if connectivity["http_ready"]
                    else "ComfyUI did not satisfy the endpoint readiness contract."
                ),
            )
            if reason == "custom_node_runtime_missing":
                if receipt is not None and install_state in {"installed", "upgrade"}:
                    report["next_steps"] = [_restart_verify_next_step(args)]
                else:
                    report["next_steps"] = [_install_next_step(args, missing_path=root is None)]
            else:
                report["next_steps"] = [_preflight_recovery_step(args, command, reason)]
            return _emit(args, report, EXIT_VERIFY)
        report.update({"status": "ok", "directly_usable": True})
        report["verify"].update({"directly_usable": True, "failure_stage": None, "failure_reason": None})
        return _emit(args, report, EXIT_OK)
    except LifecycleError as exc:
        _set_failure(
            report,
            stage=exc.stage,
            reason=exc.reason,
            message=str(exc),
            details=exc.details,
        )
        report["next_steps"] = [_preflight_recovery_step(args, command, exc.reason)]
        return _emit(args, report, exc.exit_code)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ComfyUI adapter install lifecycle")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in sorted(LIFECYCLE_COMMANDS):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--json", action="store_true")
        subparser.add_argument("--yes", action="store_true")
        subparser.add_argument("--dry-run", action="store_true")
        subparser.add_argument("--dcc-path", type=Path)
        subparser.add_argument("--python", type=Path)
        subparser.add_argument("--receipt-path", type=Path)
        subparser.add_argument("--comfyui-base-url")
        subparser.add_argument("--comfyui-timeout", type=float, default=5.0)
        subparser.add_argument("--sync-source-root", type=Path)
        subparser.add_argument("--input-dir", type=Path)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the Install SOP lifecycle command and return its stable exit code."""
    args = _build_parser().parse_args(argv)
    if args.command in {"doctor", "verify"}:
        return _run_doctor(args, args.command)
    if args.command in {"install", "upgrade"}:
        return _run_install(args, upgrade=args.command == "upgrade")
    if args.command == "status":
        return _run_status(args)
    return _run_uninstall(args)
