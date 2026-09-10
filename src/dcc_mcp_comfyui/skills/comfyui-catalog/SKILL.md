---
name: comfyui-catalog
description: Inspect ComfyUI features, node contracts, model catalogs, embeddings, and redacted runtime diagnostics. Use before constructing or adapting API-format workflows; use comfyui-workflow for execution.
metadata:
  dcc-mcp:
    dcc: comfyui
    layer: domain
    version: "0.1.5" # x-release-please-version
    tags: [comfyui, catalog, read-only]
    search-hint: "ComfyUI node types object info model folders checkpoints loras embeddings features system runtime GPU"
    tools: tools.yaml
---

# ComfyUI Catalog

Runtime contract: `dcc-mcp-core>=0.20.8,<1.0.0`. Package and CI validation do
not establish readiness of a live ComfyUI host.

Inspect the live ComfyUI capability surface without exposing process arguments,
local install paths, full queue workflows, or an unbounded object-info catalog.

Use summary tools to discover node/model names, then `get_node_type` for the one
exact node contract needed to construct an API-format workflow. Use
`comfyui-workflow` to validate and submit that workflow.
