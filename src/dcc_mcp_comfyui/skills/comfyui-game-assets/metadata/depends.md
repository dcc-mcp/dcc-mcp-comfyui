# Dependencies

- `comfyui-catalog`: inspect runtime hardware and exact node/model contracts.
- `comfyui-assets`: upload references and download prompt-owned artifacts.
- `comfyui-workflow`: query durable ComfyUI prompt status and resolve outputs.
- `comfyui-queue`: inspect queue state and cancel one exact prompt.

The recipe tools call the adapter bridge directly. These Skills provide the
user-facing observation, input, delivery and recovery steps of the full workflow.
