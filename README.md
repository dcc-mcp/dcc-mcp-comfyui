# dcc-mcp-comfyui

ComfyUI adapter for the DCC Model Context Protocol (MCP) ecosystem.

Bridges AI agents to ComfyUI workflow execution via ComfyUI's REST API.

## Quick Start

```bash
# Install
pip install dcc-mcp-comfyui

# Start ComfyUI (in another terminal)
python main.py --listen

# Start the MCP server
dcc-mcp-comfyui --comfyui-base-url http://127.0.0.1:8188
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DCC_MCP_COMFYUI_BASE_URL` | `http://127.0.0.1:8188` | ComfyUI server URL |
| `DCC_MCP_COMFYUI_TIMEOUT` | `120` | Request timeout (seconds) |
| `DCC_MCP_COMFYUI_PORT` | OS-assigned | MCP instance port |
| `DCC_MCP_GATEWAY_PORT` | `9765` | Gateway port |
| `DCC_MCP_COMFYUI_ENABLE_GATEWAY_FAILOVER` | `true` | Gateway failover |

## Skills

### comfyui-workflow

The MVP skill for ComfyUI workflow management:

- `validate_workflow` — Validate workflow JSON structure
- `submit_workflow` — Submit workflow for execution
- `query_job_status` — Poll execution status and outputs
- `get_artifact` — Get download URL for output images

## Cursor / Claude Desktop MCP Config

```json
{
  "mcpServers": {
    "dcc-mcp-comfyui": {
      "url": "http://127.0.0.1:9765/mcp"
    }
  }
}
```

## Build & Test

```bash
uv pip install -e ".[dev]"
uv run pytest
uv run ruff check src/ tests/
```

## Architecture

```
MCP Client → Gateway (:9765) → ComfyUiMcpServer (OS port)
    └─ Skill scripts → ComfyUIBridge → ComfyUI REST API (:8188)
```

## License

MIT
