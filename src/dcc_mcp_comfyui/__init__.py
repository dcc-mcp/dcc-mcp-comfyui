"""ComfyUI adapter for DCC MCP Core.

Provides MCP server bridging AI agents to ComfyUI workflow execution
via ComfyUI's REST + WebSocket API.
"""

from dcc_mcp_comfyui.__version__ import __version__
from dcc_mcp_comfyui._env import (
    DEFAULT_COMFYUI_BASE_URL,
    DEFAULT_COMFYUI_TIMEOUT,
    ENV_COMFYUI_BASE_URL,
    ENV_COMFYUI_TIMEOUT,
    ENV_ENABLE_GATEWAY_FAILOVER,
    ENV_GATEWAY_PORT,
    ENV_PORT,
    resolve_comfyui_base_url,
    resolve_comfyui_timeout,
    resolve_enable_gateway_failover,
    resolve_minimal_mode_enabled,
)
from dcc_mcp_comfyui.api import (
    ComfyUINotAvailableError,
    cf_error,
    cf_from_exception,
    cf_success,
    get_bridge,
    is_comfyui_available,
    set_bridge,
    with_comfyui,
)
from dcc_mcp_comfyui.bridge import (
    ComfyUIBridge,
    ComfyUIWorkflowError,
)
from dcc_mcp_comfyui.bridge import (
    ComfyUINotAvailableError as BridgeNotAvailableError,
)
from dcc_mcp_comfyui.server import (
    DEFAULT_PORT,
    SERVER_NAME,
    ComfyUiMcpServer,
    ComfyUiServerOptions,
    get_server,
    start_server,
    stop_server,
)

__all__ = [
    "__version__",
    "BridgeNotAvailableError",
    "cf_error",
    "cf_from_exception",
    "cf_success",
    "ComfyUIBridge",
    "ComfyUINotAvailableError",
    "ComfyUiMcpServer",
    "ComfyUiServerOptions",
    "ComfyUIWorkflowError",
    "DEFAULT_COMFYUI_BASE_URL",
    "DEFAULT_COMFYUI_TIMEOUT",
    "DEFAULT_PORT",
    "ENV_COMFYUI_BASE_URL",
    "ENV_COMFYUI_TIMEOUT",
    "ENV_ENABLE_GATEWAY_FAILOVER",
    "ENV_GATEWAY_PORT",
    "ENV_PORT",
    "get_bridge",
    "get_server",
    "is_comfyui_available",
    "resolve_comfyui_base_url",
    "resolve_comfyui_timeout",
    "resolve_enable_gateway_failover",
    "resolve_minimal_mode_enabled",
    "SERVER_NAME",
    "set_bridge",
    "start_server",
    "stop_server",
    "with_comfyui",
]
