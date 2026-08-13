---
name: comfyui-queue
description: Inspect and safely control the ComfyUI queue, exact prompt history, and memory reclamation. Cancellation and deletion always target one validated prompt ID.
metadata:
  dcc-mcp:
    dcc: comfyui
    layer: domain
    version: "0.1.0" # x-release-please-version
    tags: [comfyui, queue]
    search-hint: "ComfyUI queue running pending cancel interrupt exact prompt history delete free memory unload models"
    tools: tools.yaml
---

# ComfyUI Queue

Inspect queue identifiers and perform bounded operational recovery. Queue reads
return IDs and counts rather than full workflow bodies. Mutations validate one
exact prompt ID and verify the resulting state.

Use `cancel_prompt` for one running or pending job. Use `delete_history_entry`
only when the user wants that exact completed history record removed. Running
jobs use ComfyUI's exact job-cancel route and fail closed when that route is not
available; this Skill never falls back to the legacy global interrupt action.
