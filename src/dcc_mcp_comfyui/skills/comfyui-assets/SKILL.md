---
name: comfyui-assets
description: Upload bounded input images and atomically download artifacts proven to belong to an exact ComfyUI prompt. Use for DCC asset handoff after workflow execution.
metadata:
  dcc-mcp:
    dcc: comfyui
    layer: domain
    version: "0.1.0" # x-release-please-version
    tags: [comfyui, image, pipeline]
    search-hint: "ComfyUI upload input image download output artifact prompt ownership atomic file DCC handoff"
    tools: tools.yaml
---

# ComfyUI Assets

Move bounded files across the ComfyUI API boundary. Uploads return byte-count
and SHA-256 provenance without echoing the private source path. Downloads first
prove that prompt history owns exactly one requested artifact, stream to a
bounded same-directory partial, and atomically replace the target only after
success.
