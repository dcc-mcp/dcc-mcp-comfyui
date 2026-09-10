# Wooden crate — official ComfyUI API example

This example turns the repository's established wooden-chest prompt into a
repeatable closed wooden crate asset. It deliberately uses the built-in SD 1.5
recipe and core ComfyUI nodes only: no DCC-MCP custom node is required.

## Prerequisites

- ComfyUI reachable at `http://127.0.0.1:8188`.
- `v1-5-pruned-emaonly.safetensors` installed in `models/checkpoints`.
- This repository installed in a Python 3.10+ environment.

The checkpoint source, pinned revision, license and SHA-256 are recorded in
`src/dcc_mcp_comfyui/recipes/game_assets.json`. Model downloads are never
performed by this example.

## Reproduce

From the repository root:

```powershell
python examples/wooden-crate/run.py check
python examples/wooden-crate/run.py run --base-url http://127.0.0.1:8188 --output-dir work/wooden-crate
python examples/wooden-crate/run.py verify work/wooden-crate/receipt.json
```

`check` proves that `case.json`, the packaged recipe and the committed
`workflow_api.json` still have the same canonical SHA-256. `run` performs a
live `/object_info` preflight, submits through `/prompt`, polls `/history`,
downloads only prompt-owned artifacts through `/view`, then writes a sealed
receipt. `verify` recalculates the receipt and artifact hashes without calling
ComfyUI.

The fixed seed makes reruns comparable on the same ComfyUI/model/runtime stack;
it does not promise byte-identical inference across different GPUs or library
versions. Keep the generated receipt with review screenshots or engine import
evidence rather than committing outputs to the repository.

## Optional DCC sync

The official API run is complete without the DCC sync extension. If the
extension is installed and loaded, import the downloaded image or a later GLB
variant through the adapter's typed asset staging/sync workflow. Treat that as
a separate acceptance gate: retain the receipt, verify the asset hash again in
the target DCC, and record the target scene/object readback. Missing optional
sync support must never invalidate the official ComfyUI workflow above.
