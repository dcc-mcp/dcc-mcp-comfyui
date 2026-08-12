# dcc-mcp-comfyui

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/dcc-mcp-comfyui-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="docs/assets/dcc-mcp-comfyui.svg">
    <img src="docs/assets/dcc-mcp-comfyui.svg" alt="DCC-MCP · COMFYUI" width="600">
  </picture>
</p>

Production ComfyUI adapter for the DCC Model Context Protocol (MCP) ecosystem. It gives agents a typed, bounded path from API-format workflow validation to queue execution and artifact delivery through ComfyUI's local REST API.

![Validate, execute, and deliver a ComfyUI workflow](docs/assets/comfyui-workflow-showcase.webp)

_Illustrative workflow generated with OpenAI ImageGen from the retained source in `docs/assets/sources`; it depicts only the implemented validation, queue, polling, and artifact-delivery path._

## Capabilities

- `validate_workflow` checks API-format structure, graph references, live node classes, and required inputs against the running ComfyUI registry.
- `submit_workflow` validates before queue submission and can wait for a bounded terminal result.
- `query_job_status` returns status, node outputs, errors, and normalized artifact metadata.
- `get_artifact` builds a local download URL for a known output without exposing filesystem paths.
- Standalone discovery, packaged Skill subprocesses, and six-part DCC-MCP readiness are supported out of the box.

The production path was live-validated on ComfyUI 0.31.0 with a three-node `EmptyImage -> ImageInvert -> SaveImage` workflow, including typed CLI validation, execution, status polling, and artifact retrieval.

## Quick Start

```bash
# Install
pip install dcc-mcp-comfyui

# Start ComfyUI locally (in another terminal)
python main.py --listen 127.0.0.1

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

The bundled Skill for ComfyUI workflow management:

- `validate_workflow` — Validate workflow JSON structure
- `submit_workflow` — Submit workflow for execution
- `query_job_status` — Poll execution status and outputs
- `get_artifact` — Get download URL for output images

## MCP Client Config

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
