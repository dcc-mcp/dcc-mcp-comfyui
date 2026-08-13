---
name: comfyui-workflow
description: Validate, submit, monitor, and retrieve artifacts from ComfyUI API-format workflows through a running local ComfyUI service. Use for deterministic ComfyUI queue execution and DCC asset handoff.
metadata:
  dcc-mcp:
    dcc: comfyui
    layer: workflow
    version: "0.1.0" # x-release-please-version
    tags: [comfyui, workflow, image, automation]
    search-hint: "ComfyUI API workflow validate submit queue status output artifact image generation"
    tools: tools.yaml
---

# ComfyUI Workflow

Manage ComfyUI workflows: validate, submit, monitor status, and resolve prompt-owned output artifacts.

## Purpose

Bridge AI agents to ComfyUI's REST API for Stable Diffusion workflow automation.
This skill validates workflow JSON, submits it to ComfyUI's queue, polls for
completion, and resolves generated images for DCC asset handoff. Use
`comfyui-catalog` before authoring node graphs, `comfyui-queue` for operational
recovery, and `comfyui-assets` for bounded upload/download.

## Tools

### validate_workflow

Validate a ComfyUI API-format prompt against the running ComfyUI instance.

**Parameters:**
- `workflow` (object, required): Prompt JSON exported with **Save (API Format)**.

**Returns:** validation result with errors, warnings, and node count.

### submit_workflow

Submit a ComfyUI API-format prompt for execution. UI workflow JSON from the
regular Save action is not executable by ComfyUI's `/prompt` endpoint.

**Parameters:**
- `workflow` (object, required): Prompt JSON exported with **Save (API Format)**.
- `wait` (boolean, optional): Wait for completion before returning (default: false).
- `timeout` (number, optional): Max wait time in seconds (default: 120).

**Returns:** prompt ID, queue position, and optional execution status.

### query_job_status

Query execution status and outputs for a submitted prompt.

**Parameters:**
- `prompt_id` (string, required): The prompt ID from submit_workflow.

**Returns:** status (pending/running/completed/error), output artifacts list.

### get_artifact

Prove the exact prompt owns one matching artifact and return its download URL.

**Parameters:**
- `prompt_id` (string, required): The prompt ID.
- `filename` (string, required): Output filename.
- `subfolder` (string, optional): Subfolder path.
- `folder_type` (string, optional): 'output', 'input', or 'temp' (default: 'output').

**Returns:** download URL and artifact metadata.

## Usage

```json
{
  "search_skills": {"query": "comfyui workflow"},
  "load_skill": "comfyui-workflow",
  "call": "comfyui_workflow__submit_workflow"
}
```

## Environment

- `DCC_MCP_COMFYUI_BASE_URL`: ComfyUI server URL (default: http://127.0.0.1:8188)
- `DCC_MCP_COMFYUI_TIMEOUT`: Request timeout in seconds (default: 120)
