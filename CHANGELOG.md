# Changelog

## [0.1.0] - 2026-07-25

### Features

- Initial MVP: ComfyUI workflow adapter for DCC MCP ecosystem
- `ComfyUIBridge`: typed REST client for ComfyUI API
- `ComfyUiMcpServer`: DccServerBase subclass for MCP integration
- `comfyui-workflow` skill: validate, submit, status query, artifact retrieval
- Workflow JSON validation with cross-reference checking
- Credential isolation via `DCC_MCP_COMFYUI_BASE_URL` env var
- Bounded failure: structured error envelopes on all paths
