"""ComfyUiMcpServer — MCP server for ComfyUI workflow automation.

ComfyUI exposes a local REST API (default http://127.0.0.1:8188). This adapter
runs as a standalone sidecar that bridges typed MCP tools to bounded workflow
validation, queue execution, status, and artifact endpoints.
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from dcc_mcp_core import DccServerOptions, MinimalModeConfig
from dcc_mcp_core.server_base import DccServerBase

from dcc_mcp_comfyui.__version__ import __version__

if TYPE_CHECKING:
    from dcc_mcp_comfyui.bridge import ComfyUIBridge
from dcc_mcp_comfyui._env import (
    resolve_comfyui_base_url,
    resolve_comfyui_timeout,
)

logger = logging.getLogger(__name__)

SERVER_NAME = "dcc-mcp-comfyui"
SERVER_VERSION = __version__
DEFAULT_PORT = 0
_DCC_NAME = "comfyui"
_BUILTIN_SKILLS_DIR = Path(__file__).resolve().parent / "skills"

# Minimal mode keeps the adapter's complete typed production surface while
# excluding unrelated global skill paths.
_MINIMAL_SKILLS = (
    "comfyui-workflow",
    "comfyui-catalog",
    "comfyui-queue",
    "comfyui-assets",
)


def _configure_skill_python() -> None:
    """Keep Skill subprocesses inside the adapter's installed environment."""
    os.environ.setdefault("DCC_MCP_PYTHON_EXECUTABLE", sys.executable)


def _build_minimal_mode_config() -> MinimalModeConfig:
    return MinimalModeConfig(
        skills=_MINIMAL_SKILLS,
        deactivate_groups={},
        env_var_minimal="DCC_MCP_COMFYUI_MINIMAL",
        env_var_default_tools="DCC_MCP_COMFYUI_DEFAULT_TOOLS",
    )


@dataclass
class ComfyUiServerOptions:
    """Adapter-local options for the dcc-mcp-core server contract."""

    port: Optional[int] = None
    extra_skill_paths: Optional[list[str]] = None
    server_name: str = SERVER_NAME
    server_version: str = SERVER_VERSION
    gateway_port: Optional[int] = None
    registry_dir: Optional[str] = None
    comfyui_base_url: Optional[str] = None
    comfyui_timeout: Optional[float] = None
    enable_gateway_failover: Optional[bool] = None

    def to_core_options(self) -> DccServerOptions:
        from dcc_mcp_comfyui import _env  # noqa: PLC0415

        return DccServerOptions.from_env(
            dcc_name=_DCC_NAME,
            builtin_skills_dir=_BUILTIN_SKILLS_DIR,
            port=self.port,
            server_name=self.server_name,
            server_version=self.server_version,
            adapter_version=self.server_version,
            dcc_version=self.server_version,
            instance_type="standalone",
            standalone_main_thread=False,
            gateway_port=self.gateway_port,
            registry_dir=self.registry_dir,
            enable_gateway_failover=_env.resolve_enable_gateway_failover(self.enable_gateway_failover),
            enable_file_logging=True,
            enable_telemetry=True,
        )


class ComfyUiMcpServer(DccServerBase):
    """MCP server bridging AI agents to ComfyUI workflow execution.

    Runs as a sidecar process that connects to a running ComfyUI instance.
    Skill scripts call ComfyUI REST endpoints through the ComfyUIBridge.
    """

    def __init__(
        self,
        port: Optional[int] = None,
        extra_skill_paths: Optional[list[str]] = None,
        server_name: str = SERVER_NAME,
        server_version: str = SERVER_VERSION,
        gateway_port: Optional[int] = None,
        registry_dir: Optional[str] = None,
        comfyui_base_url: Optional[str] = None,
        comfyui_timeout: Optional[float] = None,
        enable_gateway_failover: Optional[bool] = None,
        options: Optional[ComfyUiServerOptions] = None,
    ) -> None:
        from dcc_mcp_comfyui import _env  # noqa: PLC0415

        _configure_skill_python()

        if options is None:
            options = ComfyUiServerOptions(
                port=port,
                extra_skill_paths=extra_skill_paths,
                server_name=server_name,
                server_version=server_version,
                gateway_port=gateway_port,
                registry_dir=registry_dir,
                comfyui_base_url=comfyui_base_url,
                comfyui_timeout=comfyui_timeout,
                enable_gateway_failover=enable_gateway_failover,
            )

        # Must resolve before super().__init__() — _version_string() is called
        # during DccServerBase._init_from_options().
        self._comfyui_base_url = resolve_comfyui_base_url(options.comfyui_base_url)
        self._comfyui_timeout = resolve_comfyui_timeout(options.comfyui_timeout)

        super().__init__(options=options.to_core_options())

        self._extra_skill_paths: list[str] = list(options.extra_skill_paths or [])
        self._bridge: Optional[ComfyUIBridge] = None

        if options.gateway_port == 0 or (
            options.gateway_port is None and not _env.resolve_enable_gateway_failover(options.enable_gateway_failover)
        ):
            self._config.gateway_port = 0

    # -- DccServerBase contract --

    def _version_string(self) -> str:
        return f"comfyui@{self._comfyui_base_url}"

    # -- properties --

    @property
    def comfyui_base_url(self) -> str:
        return self._comfyui_base_url

    @property
    def bridge(self) -> Optional["ComfyUIBridge"]:
        return self._bridge

    @property
    def port(self) -> int:
        if self._handle is not None:
            try:
                return int(self._handle.port)
            except Exception:
                pass
        return int(self._options.port)

    @property
    def mcp_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/mcp"

    # -- skill path collection --

    def _collect_skill_paths(self) -> list[str]:
        return self.collect_skill_search_paths(
            extra_paths=self._extra_skill_paths,
            filter_existing=True,
        )

    # -- bridge init --

    def _init_bridge(self) -> None:
        """Initialize and verify the ComfyUI bridge connection."""
        from dcc_mcp_comfyui import api  # noqa: PLC0415
        from dcc_mcp_comfyui.bridge import ComfyUIBridge  # noqa: PLC0415

        self._bridge = ComfyUIBridge(
            base_url=self._comfyui_base_url,
            timeout=self._comfyui_timeout,
        )
        try:
            self._bridge.connect()
            api.set_bridge(self._bridge)
            logger.info("ComfyUIBridge connected to %s", self._comfyui_base_url)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "ComfyUIBridge could not connect to %s (%s). Start ComfyUI and restart this adapter.",
                self._comfyui_base_url,
                exc,
            )

    # -- registration --

    def register_builtin_actions(
        self,
        extra_skill_paths: list[str] | None = None,
        include_bundled: bool = True,
        minimal_mode: MinimalModeConfig | None = None,
    ) -> None:
        from dcc_mcp_comfyui import _env  # noqa: PLC0415

        if minimal_mode is None and _env.resolve_minimal_mode_enabled():
            minimal_mode = _build_minimal_mode_config()

        super().register_builtin_actions(
            extra_skill_paths=extra_skill_paths,
            include_bundled=include_bundled,
            minimal_mode=minimal_mode,
        )

    # -- lifecycle --

    def start(self, *, install_atexit_hook: bool = True) -> "ComfyUiMcpServer":
        self._init_bridge()
        super().start(install_atexit_hook=install_atexit_hook)
        logger.info(
            "ComfyUiMcpServer started at %s (comfyui=%s)",
            self.mcp_url,
            self._comfyui_base_url,
        )
        return self

    def stop(self) -> None:
        if self._bridge is not None:
            self._bridge.disconnect()
            self._bridge = None
        super().stop()

    # -- skill management --

    def discover_skills(self, extra_paths: Optional[list[str]] = None) -> int:
        if self._handle is None:
            logger.warning("discover_skills called before server was started")
            return 0
        paths = self._collect_skill_paths()
        if extra_paths:
            paths = list(extra_paths) + paths
        return int(self._server.discover(extra_paths=paths, dcc_name=_DCC_NAME))

    def load_skill(self, skill_name: str) -> list[str]:
        if self._handle is None:
            raise RuntimeError("Server is not running — call start() first")
        return list(self._server.load_skill(skill_name))

    def list_skills(self, status: Optional[str] = None) -> list[dict[str, Any]]:
        if self._handle is None:
            return []
        return list(self._server.list_skills(status=status))


# -- module-level singleton --

_server_instance: Optional[ComfyUiMcpServer] = None


def get_server() -> Optional[ComfyUiMcpServer]:
    return _server_instance


def start_server(
    port: Optional[int] = None,
    extra_skill_paths: Optional[list[str]] = None,
    gateway_port: Optional[int] = None,
    registry_dir: Optional[str] = None,
    comfyui_base_url: Optional[str] = None,
    comfyui_timeout: Optional[float] = None,
    **kwargs: Any,
) -> ComfyUiMcpServer:
    """Start the ComfyUI MCP server singleton."""
    global _server_instance  # noqa: PLW0603

    if _server_instance is None:
        _server_instance = ComfyUiMcpServer(
            port=port,
            extra_skill_paths=extra_skill_paths,
            gateway_port=gateway_port,
            registry_dir=registry_dir,
            comfyui_base_url=comfyui_base_url,
            comfyui_timeout=comfyui_timeout,
            **kwargs,
        )
        _server_instance.register_builtin_actions()
        _server_instance.start()
    return _server_instance


def stop_server() -> None:
    """Stop the ComfyUI MCP server singleton."""
    global _server_instance  # noqa: PLW0603

    if _server_instance is not None:
        _server_instance.stop()
        _server_instance = None
