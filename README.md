# dcc-mcp-comfyui

English | [简体中文](README_zh.md)

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/dcc-mcp-comfyui-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="docs/assets/dcc-mcp-comfyui.svg">
    <img src="docs/assets/dcc-mcp-comfyui.svg" alt="DCC-MCP · COMFYUI" width="600">
  </picture>
</p>

Production ComfyUI adapter for the DCC Model Context Protocol (MCP) ecosystem. It gives agents a typed, bounded path from API-format workflow validation to queue execution and artifact delivery through ComfyUI's local REST API.

Use it to let an AI agent generate local game UI artwork, icons, transparent PNG
assets and GLB models with ComfyUI. The agent helps choose a recipe, checks the
running host, submits one job and retrieves its output for review.

![Publish a Blender mesh revision and refresh it interactively in ComfyUI Load3D](docs/assets/comfyui-3d-sync-showcase.gif)

_Real local capture: Blender sphere -> half-mesh revision -> content-addressed publish -> click-to-latest ComfyUI `Load3D` canvas preview. The reproducible single-node workflow is in [`docs/showcase/comfyui-load3d-preview.json`](docs/showcase/comfyui-load3d-preview.json)._

## Capabilities

- Nine curated local game-asset recipes cover SD1.5, SDXL, FLUX.2 Klein 4B, Z-Image Turbo, Qwen-Image 2512, BiRefNet cutouts, Hunyuan3D shapes, TRELLIS.2 PBR and Pixal3D PBR. Agents compare hardware and setup requirements, confirm the user's choice, preflight live nodes/models, and submit a bounded PNG/GLB workflow.
- Workflow validation checks API-format structure, graph references, live node classes, and required inputs before queue submission.
- Catalog discovery exposes bounded features, models, embeddings, node summaries, exact node contracts, and redacted device/runtime status.
- Queue operations inspect IDs without workflow bodies, target one exact prompt for cancellation or history deletion, and verify the resulting state; running cancellation fails closed instead of falling back to ComfyUI's legacy global interrupt.
- Asset handoff uploads bounded images with SHA-256 provenance and atomically downloads only artifacts proven to belong to the requested prompt.
- Artifact discovery is shape-based rather than tied to English labels or an image-only key, so file-shaped image, animation, video, audio, 3D, and custom-node outputs share one bounded contract.
- `stage_3d_asset` publishes a content-addressed revision from an operator-owned export root and stages it under ComfyUI `input/3d` for `Load3D`.
- The bundled ComfyUI extension adds a canvas-level **Update to latest DCC revision** action backed by an atomic latest-revision pointer.
- Standalone discovery, packaged Skill subprocesses, and six-part DCC-MCP readiness are supported out of the box.

The production path was live-validated on ComfyUI 0.32.0 with a three-node `EmptyImage -> ImageInvert -> SaveImage` workflow, including typed validation, execution, status polling, and artifact retrieval.

## Can ComfyUI MCP generate free game assets locally?

Yes, with separately installed models and compatible hardware. These nine recipes
use local ComfyUI nodes and do not require paid Partner Nodes. Model downloads,
hardware, electricity and model license conditions still apply. The adapter's MIT
license does not replace the licenses of model weights or their dependencies.

| Output or goal | Recipe | What to expect |
|---|---|---|
| Lower-cost drafts | SD1.5 (`sd15`) | 512 px image default; economical starting candidate |
| Stylized icons and illustrations | SDXL (`sdxl`) | 1024 px image default; existing checkpoint workflow |
| Fast UI artwork and concepts | FLUX.2 Klein 4B (`flux2-klein-4b`), Z-Image Turbo (`z-image-turbo`) | Modern image models; verify free VRAM before choosing |
| Detailed artwork and signs | Qwen-Image 2512 (`qwen-image-2512`) | Heavier image model; proofread generated lettering |
| Transparent PNG assets | BiRefNet (`birefnet-cutout`) | Remove an existing image's background |
| Untextured GLB shapes | Hunyuan3D 2 (`hunyuan3d-2`) | Image-to-mesh; separate license conditions |
| Textured PBR GLB props | TRELLIS.2 (`trellis2-pbr`), Pixal3D (`pixal3d-pbr`) | Image-to-3D, UVs and base-color/metallic/roughness textures |

### Which recipe fits my local GPU?

Start with the output requirement and the GPU's **free** memory. SD1.5 is the
economical image candidate; Hunyuan3D is a shape-only alternative to the more
demanding PBR pipelines. No recipe has a project-measured peak VRAM guarantee.
Weight download size is not runtime memory usage. Compare two or three suitable
options and honor the user's existing choice before downloading or generating.

Read the [selection and setup guide](src/dcc_mcp_comfyui/skills/comfyui-game-assets/references/selection-guide.en.md)
for Pixal3D, low-memory tradeoffs, licenses, input upload, OOM recovery and engine
acceptance. [中文指引](src/dcc_mcp_comfyui/skills/comfyui-game-assets/references/selection-guide.md).

### How does an agent use these recipes?

```text
Use dcc-mcp to help create a fantasy chest icon and a textured GLB prop in ComfyUI.
Inspect my available hardware and installed models. Compare suitable local recipes
and let me choose before downloading models or queuing generation. Reuse a choice
I have already made. Show the image for review before using it as the 3D reference.
Report the prompt ID, final status, artifact paths and remaining engine checks.
```

The bundled `comfyui-game-assets` Skill provides `list_asset_recipes` (offline
discovery), `prepare_asset_workflow` (live dependency checks) and `generate_asset`
(one submission). Discover and describe the tools on the selected ComfyUI instance
first. Poll the returned prompt to its terminal state, then download its artifacts.
The [shared Agent workflow](https://dcc-mcp.github.io/agents) owns CLI onboarding.

### Are the new recipes included in my installed version?

Check that the connected host exposes `comfyui-game-assets`; package version alone
is insufficient. On 2026-09-05, the recipes are merged in source at `94ccac8`, while
the latest published package, **0.1.4**, predates them. To test that merged revision
in a separate Python environment:

```bash
pip install "dcc-mcp-comfyui @ git+https://github.com/dcc-mcp/dcc-mcp-comfyui.git@94ccac8265257e74ef8c964be61fcc2bce33d3cd"
```

Then start the adapter as shown below. Follow the [release history](https://github.com/dcc-mcp/dcc-mcp-comfyui/releases)
for a packaged release containing this Skill. No model weights are installed by
this command. Source tests and CPU CI verify node contracts and a model-free PNG
roundtrip; they do not prove nine-model GPU inference, visual quality or game-ready
meshes. See the [validation record](docs/audits/2026-09-05-game-assets-geo.md).

## Quick Start

If ComfyUI is offline, the agent first explains the connection state and offers
to start/configure an existing installation or install the missing components.
It shows the setup plan and waits for your authorization. Once authorized, it
completes configuration, reconnects the adapter, discovers its tools and runs
the agreed verification; approval already given for that scope is reused.
See the [offline-host setup flow](install.md#offline-host-handoff-and-authorization).

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

The wheel includes five validated Skills and 21 typed tools:

| Skill | Tools | Boundary |
|---|---:|---|
| `comfyui-workflow` | 5 | Validate, submit, monitor, resolve prompt-owned artifacts, and stage versioned 3D assets |
| `comfyui-catalog` | 7 | Features, model folders, models, embeddings, node summaries/contracts, and redacted runtime status |
| `comfyui-queue` | 4 | Redacted queue inspection, exact cancellation/history deletion, and memory reclamation |
| `comfyui-assets` | 2 | Bounded image upload and atomic prompt-owned artifact download |
| `comfyui-game-assets` | 3 | Offline recipe discovery, live dependency preflight, and one-shot generation submission |

See the [game-asset selection and setup guide](src/dcc_mcp_comfyui/skills/comfyui-game-assets/references/selection-guide.en.md).
Recipe data includes pinned upstream workflow sources, model locations and license
notes. No weights are bundled or automatically installed. Hardware tiers are
relative guidance; preflight does not establish GPU memory fit or output quality.
Recent native 3D/background-removal nodes may require a newer ComfyUI than the
asset-sync CI baseline. Raster UI art and generated meshes still need game-engine
acceptance, including alpha edges, text, topology, collision and LODs.

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
