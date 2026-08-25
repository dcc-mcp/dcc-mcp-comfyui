"""Install SOP and verify-to-usable regression tests."""

from __future__ import annotations

import json
import subprocess
import sys
from importlib.metadata import version as distribution_version

import httpx

from dcc_mcp_comfyui import cli
from dcc_mcp_comfyui import install as install_lifecycle
from dcc_mcp_comfyui.install import load_install_sop_schema


class _Response:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.is_success = 200 <= status_code < 300

    def json(self):
        return self._payload

    def raise_for_status(self):
        if not self.is_success:
            raise httpx.HTTPStatusError(
                "request failed",
                request=httpx.Request("GET", "http://127.0.0.1:8188"),
                response=httpx.Response(self.status_code),
            )


class _HttpWithoutSyncNode:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def get(self, url, **_kwargs):
        if url.endswith("/system_stats"):
            return _Response(200, {"system": {"comfyui_version": "0.32.0"}, "devices": []})
        if url.endswith("/object_info/Load3D"):
            return _Response(200, {"Load3D": {"input": {"required": {}}}})
        return _Response(404, {}, "not found")


class _HttpWithSyncNode(_HttpWithoutSyncNode):
    def get(self, url, **kwargs):
        if url.endswith("/extensions/dcc_mcp_sync/dcc_mcp_sync.js"):
            return _Response(200, text="fetch('/dcc-mcp-sync/latest')")
        if url.endswith("/dcc-mcp-sync/latest"):
            return _Response(404, {}, "no synchronized revision is available")
        return super().get(url, **kwargs)


def _mock_python_probe(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps(
                {
                    "adapter_version": distribution_version("dcc-mcp-comfyui"),
                    "core_version": install_lifecycle.MIN_CORE_VERSION,
                    "python": sys.executable,
                }
            ),
            stderr="",
        ),
    )


def test_python_probe_fixture_tracks_installed_adapter_version(monkeypatch):
    _mock_python_probe(monkeypatch)

    completed = subprocess.run([], capture_output=True, text=True)

    assert json.loads(completed.stdout)["adapter_version"] == distribution_version("dcc-mcp-comfyui")


def test_doctor_does_not_confuse_http_with_load3d_sync_readiness(tmp_path, capsys, monkeypatch):
    source_root = tmp_path / "exports"
    input_root = tmp_path / "input"
    source_root.mkdir()
    input_root.mkdir()
    monkeypatch.setenv("DCC_MCP_COMFYUI_SYNC_SOURCE_ROOT", str(source_root))
    monkeypatch.setenv("DCC_MCP_COMFYUI_INPUT_DIR", str(input_root))
    monkeypatch.setattr(httpx, "Client", lambda **_kwargs: _HttpWithoutSyncNode())
    _mock_python_probe(monkeypatch)

    exit_code = cli.main(
        [
            "doctor",
            "--json",
            "--comfyui-base-url",
            "http://127.0.0.1:8188",
            "--python",
            sys.executable,
        ]
    )

    assert exit_code == 40
    report = json.loads(capsys.readouterr().out)
    assert report["schema_version"] == 1
    assert report["command"] == "doctor"
    assert report["connectivity"]["http_ready"] is True
    assert report["connectivity"]["load3d_ready"] is True
    assert report["connectivity"]["sync_node_ready"] is False
    assert report["verify"]["directly_usable"] is False
    assert report["verify"]["failure_reason"] == "custom_node_runtime_missing"
    assert len(report["next_steps"]) == 1
    assert report["next_steps"][0]["command"][:3] == [
        "dcc-mcp-comfyui",
        "install",
        "--json",
    ]


def test_doctor_missing_config_returns_one_executable_remediation(capsys, monkeypatch):
    monkeypatch.delenv("DCC_MCP_COMFYUI_SYNC_SOURCE_ROOT", raising=False)
    monkeypatch.delenv("DCC_MCP_COMFYUI_INPUT_DIR", raising=False)
    _mock_python_probe(monkeypatch)

    exit_code = cli.main(["doctor", "--json", "--python", sys.executable])
    report = json.loads(capsys.readouterr().out)

    assert exit_code == 10
    assert report["exit_code"] == 10
    assert report["failure_reason"] == "sync_config_missing"
    assert len(report["next_steps"]) == 1
    command = report["next_steps"][0]["command"]
    assert command[:3] == ["dcc-mcp-comfyui", "doctor", "--json"]
    assert command[-4:] == [
        "--sync-source-root",
        "<TRUSTED_EXPORT_ROOT>",
        "--input-dir",
        "<COMFYUI_INPUT_ROOT>",
    ]


def test_custom_node_receipt_round_trip_only_uninstalls_owned_files(tmp_path, capsys, monkeypatch):
    comfyui_root = tmp_path / "ComfyUI"
    (comfyui_root / "custom_nodes").mkdir(parents=True)
    (comfyui_root / "main.py").write_text("# ComfyUI\n", encoding="utf-8")
    receipt_path = tmp_path / "receipts" / "comfyui.json"
    _mock_python_probe(monkeypatch)

    install_exit = cli.main(
        [
            "install",
            "--json",
            "--yes",
            "--dcc-path",
            str(comfyui_root),
            "--python",
            sys.executable,
            "--receipt-path",
            str(receipt_path),
        ]
    )
    install_report = json.loads(capsys.readouterr().out)

    assert install_exit == 50
    assert install_report["requires_restart"] is True
    assert receipt_path.is_file()
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["dcc_type"] == "comfyui"
    assert receipt["adapter_version"] == distribution_version("dcc-mcp-comfyui")
    assert receipt["target_path"] == str((comfyui_root / "custom_nodes" / "dcc_mcp_sync").resolve())
    assert "__init__.py" in receipt["files"]

    status_exit = cli.main(["status", "--json", "--receipt-path", str(receipt_path)])
    status_report = json.loads(capsys.readouterr().out)
    assert status_exit == 0
    assert status_report["install_state"] == "installed"

    unexpected = comfyui_root / "custom_nodes" / "dcc_mcp_sync" / "operator-note.txt"
    unexpected.write_text("not owned by the receipt", encoding="utf-8")
    refused_exit = cli.main(["uninstall", "--json", "--yes", "--receipt-path", str(receipt_path)])
    refused_report = json.loads(capsys.readouterr().out)
    assert refused_exit == 10
    assert refused_report["failure_reason"] == "installed_file_set_mismatch"
    assert unexpected.is_file()
    assert receipt_path.is_file()
    unexpected.unlink()

    uninstall_exit = cli.main(["uninstall", "--json", "--yes", "--receipt-path", str(receipt_path)])
    uninstall_report = json.loads(capsys.readouterr().out)
    assert uninstall_exit == 0
    assert uninstall_report["status"] == "ok"
    assert not receipt_path.exists()
    assert not (comfyui_root / "custom_nodes" / "dcc_mcp_sync").exists()


def test_failed_upgrade_commit_restores_receipted_custom_node(tmp_path, capsys, monkeypatch):
    comfyui_root = tmp_path / "ComfyUI"
    (comfyui_root / "custom_nodes").mkdir(parents=True)
    (comfyui_root / "main.py").write_text("# ComfyUI\n", encoding="utf-8")
    receipt_path = tmp_path / "receipt.json"
    _mock_python_probe(monkeypatch)
    common = [
        "--json",
        "--yes",
        "--dcc-path",
        str(comfyui_root),
        "--python",
        sys.executable,
        "--receipt-path",
        str(receipt_path),
    ]
    assert cli.main(["install", *common]) == 50
    capsys.readouterr()
    original_receipt = receipt_path.read_bytes()
    original_init = (comfyui_root / "custom_nodes" / "dcc_mcp_sync" / "__init__.py").read_bytes()
    real_replace = install_lifecycle._replace_path

    def fail_stage_commit(source, destination):
        if source.name.startswith(".dcc_mcp_sync.stage-"):
            raise OSError("simulated commit failure")
        real_replace(source, destination)

    monkeypatch.setattr(install_lifecycle, "_replace_path", fail_stage_commit)
    exit_code = cli.main(["upgrade", *common])
    report = json.loads(capsys.readouterr().out)

    assert exit_code == 30
    assert report["failure_reason"] == "commit_failed"
    assert receipt_path.read_bytes() == original_receipt
    assert (comfyui_root / "custom_nodes" / "dcc_mcp_sync" / "__init__.py").read_bytes() == original_init


def test_doctor_uses_restart_step_for_receipted_node_not_loaded_by_host(tmp_path, capsys, monkeypatch):
    comfyui_root = tmp_path / "ComfyUI"
    source_root = tmp_path / "exports"
    input_root = tmp_path / "input"
    for path in (comfyui_root / "custom_nodes", source_root, input_root):
        path.mkdir(parents=True)
    (comfyui_root / "main.py").write_text("# ComfyUI\n", encoding="utf-8")
    receipt_path = tmp_path / "receipt.json"
    _mock_python_probe(monkeypatch)
    assert (
        cli.main(
            [
                "install",
                "--json",
                "--yes",
                "--dcc-path",
                str(comfyui_root),
                "--python",
                sys.executable,
                "--receipt-path",
                str(receipt_path),
            ]
        )
        == 50
    )
    capsys.readouterr()
    monkeypatch.setattr(httpx, "Client", lambda **_kwargs: _HttpWithoutSyncNode())

    exit_code = cli.main(
        [
            "doctor",
            "--json",
            "--python",
            sys.executable,
            "--receipt-path",
            str(receipt_path),
            "--sync-source-root",
            str(source_root),
            "--input-dir",
            str(input_root),
        ]
    )
    report = json.loads(capsys.readouterr().out)

    assert exit_code == 40
    assert report["install_state"] == "installed"
    assert report["next_steps"][0]["id"] == "restart-comfyui-and-verify"


def test_verify_fails_closed_when_receipted_custom_node_was_modified(tmp_path, capsys, monkeypatch):
    comfyui_root = tmp_path / "ComfyUI"
    source_root = tmp_path / "exports"
    input_root = tmp_path / "input"
    for path in (comfyui_root / "custom_nodes", source_root, input_root):
        path.mkdir(parents=True)
    (comfyui_root / "main.py").write_text("# ComfyUI\n", encoding="utf-8")
    receipt_path = tmp_path / "receipt.json"
    _mock_python_probe(monkeypatch)
    assert (
        cli.main(
            [
                "install",
                "--json",
                "--yes",
                "--dcc-path",
                str(comfyui_root),
                "--python",
                sys.executable,
                "--receipt-path",
                str(receipt_path),
            ]
        )
        == 50
    )
    capsys.readouterr()
    (comfyui_root / "custom_nodes" / "dcc_mcp_sync" / "operator-note.txt").write_text("not receipted", encoding="utf-8")
    monkeypatch.setattr(httpx, "Client", lambda **_kwargs: _HttpWithSyncNode())

    exit_code = cli.main(
        [
            "verify",
            "--json",
            "--python",
            sys.executable,
            "--receipt-path",
            str(receipt_path),
            "--sync-source-root",
            str(source_root),
            "--input-dir",
            str(input_root),
        ]
    )
    report = json.loads(capsys.readouterr().out)

    assert exit_code == 40
    assert report["verify"]["failure_reason"] == "installed_file_set_mismatch"
    assert report["verify"]["directly_usable"] is False


def test_packaged_install_schema_has_stable_contract():
    schema = load_install_sop_schema()

    assert schema["$id"].endswith("adapter-install-sop-v1.schema.json")
    assert schema["properties"]["schema_version"]["const"] == 1
    assert {
        "schema_version",
        "status",
        "dcc_type",
        "steps",
        "next_steps",
        "receipt_path",
        "verify",
    }.issubset(schema["required"])
