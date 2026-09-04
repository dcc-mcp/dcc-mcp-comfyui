---
name: comfyui-game-assets
description: Generate local game UI art, icons, sprites, concept images and 3D props with ComfyUI. Compare SD1.5, SDXL, FLUX.2 Klein, Z-Image, Qwen-Image, BiRefNet, Hunyuan3D, TRELLIS.2 and Pixal3D, confirm the user's choice, check installed models and nodes, then queue PNG or GLB generation. Use for free local game assets and hardware-aware setup guidance.
metadata:
  dcc-mcp:
    dcc: comfyui
    layer: domain
    version: "0.1.4" # x-release-please-version
    tags: [comfyui, game, image, 3d, pipeline]
    search-hint: "free local game assets UI icons sprites transparent PNG PBR GLB 3D Pixal3D TRELLIS Hunyuan SDXL low VRAM 免费 游戏 素材 图片 模型 本地 显存"
    tools: tools.yaml
    depends: [comfyui-workflow, comfyui-assets, comfyui-catalog, comfyui-queue]
    skill-reference-docs: [references/selection-guide.en.md, references/selection-guide.md]
---

# Local game assets

Use `list_asset_recipes` before choosing a workflow. It works without ComfyUI
and returns model sources, licenses, download sizes, hardware guidance, supported
parameters and setup steps. Runtime: Python 3.10+, `dcc-mcp-core>=0.20.8,<1.0.0`.
Package and CI validation do not establish readiness of a live ComfyUI host.

## When ComfyUI is offline or missing

First distinguish an unavailable Gateway/adapter from an unreachable ComfyUI
endpoint. A failed connection alone does not prove ComfyUI is not installed.
Explain the observed state and offer to start/configure an existing installation
or install ComfyUI and the adapter. If the installation cannot be located, ask
for its absolute path or propose an installation directory. Show the proposed
changes, selected models, download sizes and hardware requirements.

**Wait for the user's authorization before installing, downloading, starting
services or changing configuration.** Earlier authorization covering that scope
counts; do not ask again. While waiting, keep generation paused and use the
offline recipe catalog to help the user choose. A recipe choice alone is not
authorization to install its dependencies. If the user declines or defers, retain
the choice and explain how to resume.

After authorization, follow the [adapter Install SOP](https://github.com/dcc-mcp/dcc-mcp-comfyui/blob/main/install.md)
and complete the approved setup: ComfyUI/runtime dependencies, adapter connection,
selected nodes/models and startup. Rediscover the target instance and tools,
rerun recipe preflight and perform the approved bounded verification. Report
what is configured, the verification evidence and any remaining blockers. Do
not stop at supplying commands or treat installation as successful generation.

## Select, generate and deliver

1. Establish the desired asset, style, output format and available GPU/VRAM.
   Use `comfyui-catalog` runtime diagnostics when connected. Read
   [English](references/selection-guide.en.md) or
   [中文](references/selection-guide.md) for tradeoffs and prompts.
2. Present two or three suitable options with quality, memory, license and setup
   differences. **Ask the user which scheme to use before downloading weights
   or submitting generation.** A specific choice already made in this conversation
   counts; do not ask again. Do not silently change models after an OOM/failure.
3. Show the selected recipe's model list and installation steps. Local execution
   has no API fee; hardware, disk and license conditions still apply. Weight
   downloads and ComfyUI upgrades are separate operator actions; these tools do
   not install anything. Missing custom/native nodes are blockers, not permission
   to switch to a paid partner API or an unrelated UI automation provider.
4. For a reference image, use `comfyui-assets__upload_image`. Pass its exact
   relative name (`subfolder/name`, or `name` if no subfolder) to the recipe's
   `parameters.image`; upload with `folder_type=input`.
5. Call `prepare_asset_workflow` with the selected recipe and parameters. Explain
   `blockers`; source and target model folder are in `recipe.models`. An unknown
   GPU or successful preflight never proves that inference will fit in memory.
6. Call `generate_asset` with the same chosen inputs. It rechecks live contracts,
   submits once, and returns a durable ComfyUI `prompt_id`. A submitted job is
   not a completed asset. Poll `comfyui-workflow__query_job_status`; cancel only
   that prompt with `comfyui-queue__cancel_prompt`. After a transport timeout,
   inspect the queue before considering a retry.
7. Use `comfyui-assets__download_artifact` for files owned by that prompt. Keep
   the returned workflow hash, parameters, model names and download SHA-256.
   The workflow hash is not a hash of installed weights. Review output pixels,
   alpha edges or mesh/UV/PBR quality before calling it game-ready.

UI recipes generate raster art, not interactive widgets or editable layouts.
Text belongs in the engine for localization. Sprite animation consistency,
seamless tiling, retopology, rigs, collision and LODs need separate work.
