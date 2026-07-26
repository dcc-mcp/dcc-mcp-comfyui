# comfyui-workflow

Manage ComfyUI workflows: validate, submit, monitor status, and retrieve output artifacts.

## Purpose

Bridge AI agents to ComfyUI's REST API for Stable Diffusion workflow automation.
This skill provides the MVP vertical slice: validate workflow JSON, submit to
ComfyUI's queue, poll for completion, and retrieve generated images for DCC asset handoff.

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

Get download URL for a specific output artifact.

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
