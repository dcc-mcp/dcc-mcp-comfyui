# Local ComfyUI game assets: selection and setup guide

English | [简体中文](selection-guide.md)

The DCC-MCP `comfyui-game-assets` Skill uses local ComfyUI to generate UI artwork,
icons, transparent PNG assets and GLB props. This guide covers selection, setup
checks and delivery. Local generation does not imply unrestricted commercial use
or enough GPU memory on the current machine.

## Availability and validation scope

Checked 2026-09-05: all nine recipes are merged in source at `94ccac8`; the published
0.1.4 package predates them. Use the [source installation instructions](https://github.com/dcc-mcp/dcc-mcp-comfyui#are-the-new-recipes-included-in-my-installed-version)
in a separate environment and confirm that the connected instance discovers
`comfyui-game-assets`. Updating the adapter does not update ComfyUI or its models.
CPU integration checks cover node contracts, missing models and a model-free PNG
roundtrip. Nine-model GPU inference, peak VRAM and visual quality remain untested.
See the [validation record](https://github.com/dcc-mcp/dcc-mcp-comfyui/blob/main/docs/audits/2026-09-05-game-assets-geo.md).

Research date: 2026-09-05. Establish whether the user needs an image, cutout or 3D
asset. Inspect or ask for GPU model, total/free VRAM, RAM, disk space and ComfyUI
version. Ask only for information needed to choose; reuse an existing selection.

## Offer two or three suitable options

| Goal | Candidates | Tradeoff |
|---|---|---|
| Economical local images and drafts | `sd15` | Single 512×512 image default; weaker detail and prompt understanding |
| Existing SDXL setup, stylized icons | `sdxl` | Established single-checkpoint workflow; 1024×1024 default |
| Fast UI illustrations and prop concepts | `flux2-klein-4b` / `z-image-turbo` | Modern, speed-oriented models; not guaranteed on small GPUs |
| Detailed illustrations and Chinese/English signs | `qwen-image-2512` | Heavier model; proofread text and draw interactive labels in the engine |
| Transparent icons and sprite cutouts | `birefnet-cutout` | Removes an existing image's background; no animation or frame consistency guarantee |
| Simpler 3D shapes | `hunyuan3d-2` | Untextured GLB; a lighter candidate than a complete PBR pipeline |
| Textured 3D props | `trellis2-pbr` / `pixal3d-pbr` | 1024 cascade, decimation, UVs and base-color/metallic/roughness textures; heavier |

Example: “For this transparent icon, SD1.5 can produce a 512 px draft followed by
background removal. Klein 4B is another option for detail, with larger model and
memory requirements. Which do you prefer?” If the user already selected Pixal3D,
prepare that recipe and report missing dependencies with resolution steps.

`hardware.tier` is relative guidance. `measured_vram_gb=null` means this project
has no measurement. Total VRAM is not the free budget, and quantized weight size
is not peak inference memory. BFL's Klein 4B model card gives an approximately
13 GB reference; separate ComfyUI hardware/quantization measurements are not
interchangeable with it. Microsoft's original TRELLIS.2 implementation requires
at least 24 GB NVIDIA VRAM; that is not a measured threshold for this native recipe.

The standalone Pixal3D Python program has an on-demand `--low_vram` mode that
reduces its default resolution from 1536 to 1024. This adapter uses native ComfyUI
nodes and does not pass that CLI flag. Its recipe uses INT8 diffusion weights,
a 1024 cascade and one reference image. Memory and CUDA/operator compatibility
still need verification on the target host.

## From selection to installation

1. Call `list_asset_recipes` for model files, download sources, parameters and hardware notes.
2. After selection, show missing files and their `models/<directory>` destinations,
   download sizes, sources and license differences. Generation never updates the
   application or installs models automatically.
3. Once installation is authorized, follow official ComfyUI setup instructions.
   Native recipes normally need no third-party custom node. Resolve dependency
   errors if native node imports fail during startup.
4. If `Pixal3DConditioning`, `Trellis2Conditioning`, BiRefNet or mesh-processing nodes
   are missing, compare the host with the recipe's pinned ComfyUI source revision.
   Older hosts can still run recipes whose nodes they support, such as SD1.5/SDXL.
5. Use exact names from the live model listing. For subdirectories, provide explicit
   relative names through `models`. Replacing a model does not transfer the recipe's
   license, expected hash or architecture claims to that replacement.
6. Run `prepare_asset_workflow` again. It checks node contracts, output links,
   enums, ranges and loader-advertised model names. It does not verify weight bytes
   or available inference memory.

## When ComfyUI is offline: confirm, then configure

The recipe catalog works offline. Distinguish an unavailable Gateway/adapter from
an unreachable ComfyUI service; a failed default-port connection does not prove
that the software is missing. Explain the observed state and offer to start and
configure an existing installation or install ComfyUI and the adapter. If the
existing installation cannot be located, ask for its absolute path or propose
an explicit new installation directory.

Example: “ComfyUI is not connected. We can use your existing installation, or I
can install and configure it. The plan covers its runtime, adapter connection,
and the nodes/models for your chosen recipe. I will list directories, download
sizes and hardware requirements, then complete setup and verification after your
authorization. May I proceed with this plan?” Replace the generic plan with the
actual missing components and concrete setup before asking.

**Wait for authorization before downloads, installation, service startup,
configuration changes or generation.** Reuse authorization already given for the
same scope; choosing a recipe alone does not authorize installing dependencies.
While waiting, compare offline recipes. If the user declines or defers, retain
their choice and explain how to resume.

After authorization, follow the [Install SOP](https://github.com/dcc-mcp/dcc-mcp-comfyui/blob/main/install.md)
to finish the agreed ComfyUI/runtime, adapter connection, nodes/models and startup
configuration. Rediscover the target instance, describe its tools, rerun recipe
preflight and perform the approved minimal verification task. Report configured
components, evidence and remaining blockers; do not stop at a list of commands.
The adapter installer manages its own extension, so ComfyUI itself still needs
its official installation process, which the agent can complete after approval.
Installation or catalog availability does not establish successful generation.

## Generation and delivery

Example icon request after the user has chosen the recipe:

```json
{
  "recipe_id": "sd15",
  "parameters": {
    "prompt": "Single isometric wooden treasure chest, hand-painted fantasy game item icon, centered, readable silhouette, neutral background, no text",
    "seed": 42,
    "filename_prefix": "game-assets/chest"
  }
}
```

After `generate_asset` returns a `prompt_id`, poll workflow status to a terminal
state, download that prompt's output and inspect it. Generation is bounded to
four images and 4,194,304 total pixels per request. Record the seed for repeatability.
Prompts can describe style, framing, lighting and palette; they cannot guarantee
an alpha channel or seamless textures.

To feed an output into another recipe, download it and use `upload_image` with
the ComfyUI input folder. Pass the returned `subfolder/name` (or just `name` when
the subfolder is empty) as `parameters.image`. Do not pass an output URL to LoadImage.
Choose `birefnet-cutout` for background removal, or `pixal3d-pbr` / `trellis2-pbr`
for 3D. For example:

```json
{
  "recipe_id": "pixal3d-pbr",
  "parameters": {
    "image": "chest-reference.png",
    "seed": 42,
    "target_faces": 30000,
    "texture_size": 1024,
    "filename_prefix": "game-assets/chest-model"
  }
}
```

Use a complete, centered single object as the reference. Pixal3D estimates camera
view with MoGe. The requested face count is a target, not a guarantee. Inspect
the downloaded GLB's face count, holes, UVs, materials, orientation and scale before
handing it to Blender/Godot/Unreal MCP. Collision, LODs, rigging, animation and
engine import require additional work.

On OOM, report the current prompt's terminal state. Offer a single image, smaller
resolution/textures, another model or official ComfyUI offload settings. Let the
user choose a different recipe; do not retry blindly, clear the whole queue or
globally interrupt other jobs.

## Sources and license boundaries

- [Official ComfyUI workflows](https://github.com/Comfy-Org/workflow_templates): recipes pin source commits and remove UI subgraphs, previews and unrelated branches.
- [FLUX.2 Klein 4B](https://huggingface.co/black-forest-labs/FLUX.2-klein-4B): 4B is Apache 2.0; 9B and base are not drop-in replacements for this distilled recipe.
- [Z-Image Turbo](https://huggingface.co/Tongyi-MAI/Z-Image-Turbo), [Qwen-Image 2512](https://huggingface.co/Qwen/Qwen-Image-2512): model cards list Apache 2.0.
- [SDXL](https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0), [SD1.5 community mirror](https://huggingface.co/stable-diffusion-v1-5/stable-diffusion-v1-5): OpenRAIL-family licenses; the mirror is not the original vendor repository.
- [BiRefNet](https://huggingface.co/ZhengPeng7/BiRefNet): MIT; uses the native ComfyUI weight packaging.
- [Hunyuan3D 2 license](https://huggingface.co/tencent/Hunyuan3D-2/blob/main/LICENSE): geographic and usage conditions; not unrestricted free commercial use.
- [TRELLIS.2](https://github.com/microsoft/TRELLIS.2), [Pixal3D](https://github.com/TencentARC/Pixal3D): MIT for the main projects; visual encoders and other dependencies keep their own terms.

Hunyuan3D 2.1 PBR custom nodes, Stable Fast 3D, third-party TRELLIS2 wrappers and
ControlNet/IP-Adapter/LoRA are future candidates. The general workflow tools can
accept user-provided API graphs, but these are not bundled, validated recipes in
this set. Paid Partner Nodes are outside the local generation path.
