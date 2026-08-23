# dcc-mcp-comfyui

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/dcc-mcp-comfyui-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="docs/assets/dcc-mcp-comfyui.svg">
    <img src="docs/assets/dcc-mcp-comfyui.svg" alt="DCC-MCP · COMFYUI" width="600">
  </picture>
</p>

Production ComfyUI adapter for the DCC Model Context Protocol (MCP) ecosystem. It gives agents a typed, bounded path from API-format workflow validation to queue execution and artifact delivery through ComfyUI's local REST API.

![Publish a Blender mesh revision and refresh it interactively in ComfyUI Load3D](docs/assets/comfyui-3d-sync-showcase.gif)

_Real local capture: Blender sphere -> half-mesh revision -> content-addressed publish -> click-to-latest ComfyUI `Load3D` canvas preview. The reproducible single-node workflow is in [`docs/showcase/comfyui-load3d-preview.json`](docs/showcase/comfyui-load3d-preview.json)._

## Capabilities

- Workflow validation checks API-format structure, graph references, live node classes, and required inputs before queue submission.
- Catalog discovery exposes bounded features, models, embeddings, node summaries, exact node contracts, and redacted device/runtime status.
- Queue operations inspect IDs without workflow bodies, target one exact prompt for cancellation or history deletion, and verify the resulting state; running cancellation fails closed instead of falling back to ComfyUI's legacy global interrupt.
- Asset handoff uploads bounded images with SHA-256 provenance and atomically downloads only artifacts proven to belong to the requested prompt.
- Artifact discovery is shape-based rather than tied to English labels or an image-only key, so file-shaped image, animation, video, audio, 3D, and custom-node outputs share one bounded contract.
- `stage_3d_asset` publishes a content-addressed revision from an operator-owned export root and stages it under ComfyUI `input/3d` for `Load3D`.
- The bundled ComfyUI extension adds a canvas-level **Update to latest DCC revision** action backed by an atomic latest-revision pointer.
- Standalone discovery, packaged Skill subprocesses, and six-part DCC-MCP readiness are supported out of the box.

The production path was live-validated on ComfyUI 0.32.0 with a three-node `EmptyImage -> ImageInvert -> SaveImage` workflow, including typed validation, execution, status polling, and artifact retrieval.

## Quick Start

See the canonical [agent-first Install SOP](install.md) for JSON doctor,
transactional custom-node installation, verify, upgrade, and uninstall.

```bash
# Install
pip install dcc-mcp-comfyui

# Install the bundled Load3D sync node (plan first, then repeat with --yes)
dcc-mcp-comfyui install --json --dry-run --dcc-path /absolute/path/to/ComfyUI

# Start ComfyUI locally (in another terminal)
python main.py --listen 127.0.0.1

# Start the MCP server
dcc-mcp-comfyui --comfyui-base-url http://127.0.0.1:8188
```

To enable bounded 3D synchronization, configure both trusted roots before
starting the adapter:

```bash
set DCC_MCP_COMFYUI_SYNC_SOURCE_ROOT=G:\dcc-sync\exports
set DCC_MCP_COMFYUI_INPUT_DIR=G:\apps\ComfyUI\input
dcc-mcp-comfyui --comfyui-base-url http://127.0.0.1:8188
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DCC_MCP_COMFYUI_BASE_URL` | `http://127.0.0.1:8188` | ComfyUI server URL |
| `DCC_MCP_COMFYUI_TIMEOUT` | `120` | Request timeout (seconds) |
| `DCC_MCP_COMFYUI_SYNC_SOURCE_ROOT` | unset | Trusted producer-export root required by `stage_3d_asset` |
| `DCC_MCP_COMFYUI_INPUT_DIR` | unset | Trusted ComfyUI input root required by `stage_3d_asset` |
| `DCC_MCP_COMFYUI_SYNC_MAX_ASSET_BYTES` | `268435456` | Maximum accepted 3D asset size |
| `DCC_MCP_COMFYUI_PORT` | OS-assigned | MCP instance port |
| `DCC_MCP_GATEWAY_PORT` | `9765` | Gateway port |
| `DCC_MCP_COMFYUI_ENABLE_GATEWAY_FAILOVER` | `true` | Gateway failover |

## Skills

The wheel includes four validated Skills and 18 typed tools:

| Skill | Tools | Boundary |
|---|---:|---|
| `comfyui-workflow` | 5 | Validate, submit, monitor, resolve prompt-owned artifacts, and stage versioned 3D assets |
| `comfyui-catalog` | 7 | Features, model folders, models, embeddings, node summaries/contracts, and redacted runtime status |
| `comfyui-queue` | 4 | Redacted queue inspection, exact cancellation/history deletion, and memory reclamation |
| `comfyui-assets` | 2 | Bounded image upload and atomic prompt-owned artifact download |

The public surface does not expose arbitrary Python, raw process arguments,
local ComfyUI install paths, bulk queue deletion, or unbounded catalog dumps.

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
    ├─ Workflow scripts → ComfyUIBridge → ComfyUI REST API (:8188)
    └─ Asset sync → content-addressed revision → configured ComfyUI input/3d
```

## License

MIT
