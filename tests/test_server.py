"""Basic tests for dcc-mcp-comfyui (no live ComfyUI required)."""

from __future__ import annotations

import os
import sys
from importlib.metadata import version
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest
from dcc_mcp_core import validate_skill


def test_import():
    import dcc_mcp_comfyui

    assert dcc_mcp_comfyui.__version__ == version("dcc-mcp-comfyui")


def test_cli_version(capsys):
    from dcc_mcp_comfyui import __version__
    from dcc_mcp_comfyui.cli import main

    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])

    assert exc_info.value.code == 0
    assert capsys.readouterr().out.strip() == __version__


def test_api_imports():
    from dcc_mcp_comfyui import (
        ComfyUIBridge,
        ComfyUiMcpServer,
        cf_error,
        cf_success,
        is_comfyui_available,
    )

    assert callable(ComfyUiMcpServer)
    assert callable(ComfyUIBridge)
    assert callable(cf_success)
    assert callable(cf_error)
    assert callable(is_comfyui_available)


def test_is_comfyui_available_false_initially():
    from dcc_mcp_comfyui import is_comfyui_available

    assert is_comfyui_available() is False


def test_cf_success():
    from dcc_mcp_comfyui import cf_success

    result = cf_success("workflow validated", prompt_id="abc123", node_count=5)
    assert result["success"] is True
    assert result["message"] == "workflow validated"


def test_cf_error():
    from dcc_mcp_comfyui import cf_error

    result = cf_error("validation failed", error="Missing nodes key")
    assert result["success"] is False


def test_get_bridge_raises_when_not_set():
    from dcc_mcp_comfyui.api import ComfyUINotAvailableError, get_bridge

    with pytest.raises(ComfyUINotAvailableError):
        get_bridge()


def test_resolve_comfyui_base_url_default():
    from dcc_mcp_comfyui._env import DEFAULT_COMFYUI_BASE_URL, resolve_comfyui_base_url

    assert resolve_comfyui_base_url() == DEFAULT_COMFYUI_BASE_URL


def test_resolve_comfyui_base_url_from_arg():
    from dcc_mcp_comfyui._env import resolve_comfyui_base_url

    assert resolve_comfyui_base_url("http://10.0.0.1:8188") == "http://10.0.0.1:8188"


def test_resolve_comfyui_base_url_from_env(monkeypatch):
    from dcc_mcp_comfyui._env import resolve_comfyui_base_url

    monkeypatch.setenv("DCC_MCP_COMFYUI_BASE_URL", "http://remote:8188")
    assert resolve_comfyui_base_url() == "http://remote:8188"


def test_resolve_comfyui_timeout_default():
    from dcc_mcp_comfyui._env import DEFAULT_COMFYUI_TIMEOUT, resolve_comfyui_timeout

    assert resolve_comfyui_timeout() == DEFAULT_COMFYUI_TIMEOUT


def test_resolve_comfyui_timeout_from_env(monkeypatch):
    from dcc_mcp_comfyui._env import resolve_comfyui_timeout

    monkeypatch.setenv("DCC_MCP_COMFYUI_TIMEOUT", "60")
    assert resolve_comfyui_timeout() == 60.0


def test_resolve_minimal_mode_enabled_default():
    from dcc_mcp_comfyui._env import resolve_minimal_mode_enabled

    assert resolve_minimal_mode_enabled() is True


def test_resolve_minimal_mode_disabled(monkeypatch):
    from dcc_mcp_comfyui._env import resolve_minimal_mode_enabled

    monkeypatch.setenv("DCC_MCP_MINIMAL", "0")
    assert resolve_minimal_mode_enabled() is False


# -- server construction tests --


@pytest.mark.parametrize(("port", "expected"), [(None, 8765), (0, 0)])
def test_server_dynamic_port_and_explicit_zero(monkeypatch, port, expected):
    from dcc_mcp_comfyui import ComfyUiMcpServer

    monkeypatch.setenv("DCC_MCP_COMFYUI_PORT", "8765")
    server = ComfyUiMcpServer(port=port)
    assert server._config.port == expected


def test_server_construction_with_custom_base_url():
    from dcc_mcp_comfyui import ComfyUiMcpServer

    server = ComfyUiMcpServer(comfyui_base_url="http://192.168.1.1:8188")
    assert server.comfyui_base_url == "http://192.168.1.1:8188"


@patch("dcc_mcp_comfyui.server.ComfyUiMcpServer.start")
@patch("dcc_mcp_comfyui.server.ComfyUiMcpServer.register_builtin_actions")
def test_start_server_singleton(mock_register, mock_start):
    import dcc_mcp_comfyui.server as server_mod
    from dcc_mcp_comfyui import start_server, stop_server

    server_mod._server_instance = None
    mock_start.return_value = MagicMock(mcp_url="http://127.0.0.1:9876/mcp", comfyui_base_url="http://127.0.0.1:8188")

    handle = start_server(port=9876)
    assert handle is not None
    mock_register.assert_called_once()
    mock_start.assert_called_once()

    stop_server()
    assert server_mod._server_instance is None


def test_server_options_to_core_options():
    from dcc_mcp_comfyui.server import ComfyUiServerOptions

    opts = ComfyUiServerOptions(
        port=8123,
        registry_dir="C:/isolated/comfyui-registry",
        comfyui_base_url="http://localhost:8188",
    )
    core_opts = opts.to_core_options()
    assert core_opts.port == 8123
    assert core_opts.dcc_name == "comfyui"
    assert core_opts.instance_type == "standalone"
    assert core_opts.gateway.registry_dir == "C:/isolated/comfyui-registry"
    assert core_opts.gateway.dcc_version == version("dcc-mcp-comfyui")
    assert core_opts.sidecar.adapter_version == version("dcc-mcp-comfyui")


def test_skill_python_defaults_to_active_environment(monkeypatch):
    from dcc_mcp_comfyui.server import _configure_skill_python

    monkeypatch.delenv("DCC_MCP_PYTHON_EXECUTABLE", raising=False)

    _configure_skill_python()

    assert os.environ["DCC_MCP_PYTHON_EXECUTABLE"] == sys.executable


def test_explicit_skill_python_is_preserved(monkeypatch):
    from dcc_mcp_comfyui.server import _configure_skill_python

    monkeypatch.setenv("DCC_MCP_PYTHON_EXECUTABLE", "C:/explicit/python.exe")

    _configure_skill_python()

    assert os.environ["DCC_MCP_PYTHON_EXECUTABLE"] == "C:/explicit/python.exe"


def test_bundled_workflow_skill_validates_without_issues():
    skill = Path(__file__).parents[1] / "src" / "dcc_mcp_comfyui" / "skills" / "comfyui-workflow"

    report = validate_skill(str(skill))

    assert not report.has_errors
    assert not report.issues


# -- bridge unit tests --


class TestComfyUIBridge:
    def test_construction(self):
        from dcc_mcp_comfyui.bridge import ComfyUIBridge

        bridge = ComfyUIBridge(base_url="http://127.0.0.1:8188")
        assert bridge.base_url == "http://127.0.0.1:8188"
        assert bridge.client_id is not None
        assert bridge.ws_url.startswith("ws://")

    def test_ping_fails_when_server_down(self):
        from dcc_mcp_comfyui.bridge import ComfyUIBridge

        bridge = ComfyUIBridge(base_url="http://127.0.0.1:19999")
        assert bridge.ping() is False

    def test_connect_raises_when_server_down(self):
        from dcc_mcp_comfyui.bridge import ComfyUIBridge, ComfyUINotAvailableError

        bridge = ComfyUIBridge(base_url="http://127.0.0.1:19999", timeout=1.0)
        with pytest.raises(ComfyUINotAvailableError):
            bridge.connect()

    def test_validate_workflow_empty_prompt(self):
        from dcc_mcp_comfyui.bridge import ComfyUIBridge

        bridge = ComfyUIBridge()
        result = bridge.validate_workflow({})
        assert result["valid"] is False
        assert any("node" in e.lower() for e in result["errors"])

    def test_validate_workflow_not_dict(self):
        from dcc_mcp_comfyui.bridge import ComfyUIBridge

        bridge = ComfyUIBridge()
        result = bridge.validate_workflow("not a dict")
        assert result["valid"] is False

    def test_validate_workflow_valid_shape(self, monkeypatch):
        from dcc_mcp_comfyui.bridge import ComfyUIBridge

        bridge = ComfyUIBridge()
        monkeypatch.setattr(bridge, "get_object_info", lambda: {})
        workflow = {
            "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "v1-5.safetensors"}},
            "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "a cat", "clip": ["1", 0]}},
            "3": {"class_type": "VAEDecode", "inputs": {"samples": ["2", 0], "vae": ["1", 0]}},
            "4": {"class_type": "SaveImage", "inputs": {"images": ["3", 0]}},
        }
        result = bridge.validate_workflow(workflow)
        assert result["valid"] is True
        assert result["node_count"] == 4

    def test_validate_workflow_reports_missing_required_inputs(self, monkeypatch):
        from dcc_mcp_comfyui.bridge import ComfyUIBridge

        bridge = ComfyUIBridge()
        monkeypatch.setattr(
            bridge,
            "get_object_info",
            lambda: {
                "EmptyImage": {
                    "input": {
                        "required": {
                            "width": ["INT", {"default": 512}],
                            "height": ["INT", {"default": 512}],
                            "batch_size": ["INT", {"default": 1}],
                            "color": ["INT", {"default": 0}],
                        }
                    }
                }
            },
        )

        result = bridge.validate_workflow(
            {
                "1": {
                    "class_type": "EmptyImage",
                    "inputs": {"width": 64, "height": 64, "batch_size": 1},
                }
            }
        )

        assert result["valid"] is False
        assert result["errors"] == ["Node 1 is missing required input 'color'"]

    def test_validate_workflow_rejects_ui_graph_shape(self):
        from dcc_mcp_comfyui.bridge import ComfyUIBridge

        bridge = ComfyUIBridge()
        workflow = {
            "nodes": [
                {"id": 1, "class_type": "CheckpointLoaderSimple", "inputs": {}},
            ]
        }
        result = bridge.validate_workflow(workflow)
        assert result["valid"] is False
        assert any("API format" in error for error in result["errors"])

    def test_validate_workflow_bad_reference(self):
        from dcc_mcp_comfyui.bridge import ComfyUIBridge

        bridge = ComfyUIBridge()
        workflow = {
            "1": {"class_type": "VAEDecode", "inputs": {"samples": ["99", 0]}},
        }
        result = bridge.validate_workflow(workflow)
        assert result["valid"] is False
        assert any("99" in e for e in result["errors"])

    def test_get_artifact_url(self):
        from dcc_mcp_comfyui.bridge import ComfyUIBridge

        bridge = ComfyUIBridge(base_url="http://127.0.0.1:8188")
        url = bridge.get_artifact_url("render & final.png", subfolder="my folder/alpha", folder_type="output")
        assert parse_qs(urlparse(url).query) == {
            "filename": ["render & final.png"],
            "subfolder": ["my folder/alpha"],
            "type": ["output"],
        }

    @patch("httpx.Client")
    def test_ping_success(self, mock_client_cls):
        from dcc_mcp_comfyui.bridge import ComfyUIBridge

        mock_resp = MagicMock()
        mock_resp.is_success = True
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.get.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        bridge = ComfyUIBridge()
        assert bridge.ping() is True

    @patch("httpx.Client")
    def test_get_object_info(self, mock_client_cls):
        from dcc_mcp_comfyui.bridge import ComfyUIBridge

        mock_resp = MagicMock()
        mock_resp.is_success = True
        mock_resp.json.return_value = {"CheckpointLoaderSimple": {"input": {}}}
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.get.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        bridge = ComfyUIBridge()
        bridge._connected = True
        info = bridge.get_object_info()
        assert "CheckpointLoaderSimple" in info

    @patch("httpx.Client")
    def test_submit_workflow(self, mock_client_cls):
        from dcc_mcp_comfyui.bridge import ComfyUIBridge

        mock_resp = MagicMock()
        mock_resp.is_success = True
        mock_resp.json.return_value = {"prompt_id": "test-prompt-123", "number": 1, "node_errors": {}}
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.post.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        bridge = ComfyUIBridge()
        workflow = {"1": {"class_type": "SaveImage", "inputs": {}}}
        result = bridge.submit_workflow(workflow)
        assert result["prompt_id"] == "test-prompt-123"
        assert result["number"] == 1
        mock_client.post.assert_called_once_with(
            "http://127.0.0.1:8188/prompt",
            json={"prompt": workflow, "client_id": bridge.client_id},
        )

    @patch("httpx.Client")
    def test_get_prompt_status_completed(self, mock_client_cls):
        from dcc_mcp_comfyui.bridge import ComfyUIBridge

        mock_resp = MagicMock()
        mock_resp.is_success = True
        mock_resp.json.return_value = {
            "test-1": {
                "status": {"completed": True, "status_str": "success"},
                "outputs": {"4": {"images": [{"filename": "out_00001_.png", "subfolder": "", "type": "output"}]}},
            }
        }
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.get.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        bridge = ComfyUIBridge()
        status = bridge.get_prompt_status("test-1")
        assert status["done"] is True
        assert status["status"] == "completed"
        assert "4" in status["outputs"]

    @patch("httpx.Client")
    def test_get_prompt_status_not_found(self, mock_client_cls):
        from dcc_mcp_comfyui.bridge import ComfyUIBridge

        mock_resp = MagicMock()
        mock_resp.is_success = True
        mock_resp.json.return_value = {}
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.get.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        bridge = ComfyUIBridge()
        status = bridge.get_prompt_status("nonexistent")
        assert status["status"] == "not_found"
        assert status["done"] is False

    def test_validate_workflow_with_cross_reference(self, monkeypatch):
        """Validate a realistic multi-node workflow with proper cross-references."""
        from dcc_mcp_comfyui.bridge import ComfyUIBridge

        # Mock get_node_names to avoid HTTP call
        bridge = ComfyUIBridge()
        monkeypatch.setattr(
            bridge,
            "get_node_names",
            lambda: [
                "CheckpointLoaderSimple",
                "CLIPTextEncode",
                "KSampler",
                "VAEDecode",
                "SaveImage",
                "EmptyLatentImage",
            ],
        )

        workflow = {
            "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "v1-5-pruned.safetensors"}},
            "2": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512, "batch_size": 1}},
            "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "a beautiful landscape", "clip": ["1", 1]}},
            "4": {"class_type": "CLIPTextEncode", "inputs": {"text": "bad quality", "clip": ["1", 1]}},
            "5": {
                "class_type": "KSampler",
                "inputs": {
                    "seed": 42,
                    "steps": 20,
                    "cfg": 7.0,
                    "sampler_name": "euler",
                    "scheduler": "normal",
                    "denoise": 1.0,
                    "model": ["1", 0],
                    "positive": ["3", 0],
                    "negative": ["4", 0],
                    "latent_image": ["2", 0],
                },
            },
            "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
            "7": {"class_type": "SaveImage", "inputs": {"images": ["6", 0], "filename_prefix": "result"}},
        }
        result = bridge.validate_workflow(workflow)
        assert result["valid"] is True
        assert result["node_count"] == 7
