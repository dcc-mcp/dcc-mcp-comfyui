# 方案选择与使用指引

调研日期：2026-09-05。先确认用户要图片、透明素材还是 3D，再询问或读取
GPU 型号、总显存/空闲显存、内存、磁盘空间和 ComfyUI 版本。仅在这些信息
不足以做选择时询问用户；已经选定的方案不要重复确认。

## 给用户两三个选项

| 目标 | 候选 | 取舍 |
|---|---|---|
| 本地低负担图片、草稿 | `sd15` | 默认 512×512、单张，细节和提示词理解较弱 |
| 已有 SDXL、风格化图标 | `sdxl` | 成熟的单 checkpoint 流程，默认 1024×1024 |
| 快速 UI 插画、道具概念图 | `flux2-klein-4b` / `z-image-turbo` | 现代模型，速度优先；并非小显存必然可运行 |
| 复杂插画、中文或英文招牌 | `qwen-image-2512` | 较重的模型；文字仍需校对，交互文字由游戏引擎绘制 |
| 透明 PNG 图标、精灵切图 | `birefnet-cutout` | 对已有图片去背景；不能生成动画序列或保证帧间一致性 |
| 较简单的 3D 形状 | `hunyuan3d-2` | 无贴图 GLB；可作为比完整 PBR 管线更轻的候选 |
| 带材质的 3D 道具 | `trellis2-pbr` / `pixal3d-pbr` | 1024 级联、减面、UV、基础色/金属度/粗糙度；更重 |

可以这样确认：“这次需要透明图标。可先用 SD1.5 做 512 像素草稿，再去背景；
也可以用 Klein 4B 追求更好的细节，但模型和显存需求更高。你选哪一种？”
用户已经指名 Pixal3D 时，直接准备 Pixal3D；如果缺依赖，展示缺项与解决步骤。

`hardware.tier` 是相对推荐级别，`measured_vram_gb=null` 表示本项目没有实测。
不要把显存总量直接当成可用预算，或把量化权重大小当成推理峰值。
BFL 模型卡给出 Klein 4B 约 13 GB 的参考值；ComfyUI 文档另有特定硬件/量化
测量，二者不应混用。Microsoft 的 TRELLIS.2 原始实现要求至少 24 GB NVIDIA
显存，其数值也不是这里原生 ComfyUI 配方的实测门槛。

Pixal3D 官方的独立 Python 程序提供按需加载的 `--low_vram`，默认从 1536
降为 1024；本适配器走 ComfyUI 原生节点，不传递该 CLI 参数。原生配方采用
INT8 扩散模型、1024 级联、单个参考图；实际内存、CUDA/算子兼容性仍需验证。

## 从选择到安装

1. 调用 `list_asset_recipes` 获取完整模型清单、下载来源、参数和硬件提示。
2. 用户选择后，列出缺失文件与 `models/<directory>` 目标目录；让用户知晓
   下载体积、模型来源和许可差异。模型和主程序更新不由生成工具自动执行。
3. 用户授权安装后，按官方 ComfyUI 安装方式准备节点和权重。原生配方通常
   不需要第三方 custom node；如果启动时节点导入失败，要解决其依赖错误。
4. 当前实例缺少 `Pixal3DConditioning`、`Trellis2Conditioning`、BiRefNet 或
   网格后处理节点时，参考配方固定的 ComfyUI 源码版本检查升级需求。
   旧版本仍然可以使用支持的 SD1.5/SDXL 等配方。
5. 使用模型列表中的确切名称；放在子目录时，通过 `models` 显式指定相对名。
   覆盖文件后，原配方许可、下载 SHA 和架构不自动适用于替换模型。
6. 再次调用 `prepare_asset_workflow`。它只读检查节点契约、连接输出、枚举、
   数值范围及 loader 宣告的权重列表；不校验实际权重内容或可用显存。

网络不可用时目录仍能查询。ComfyUI 不在线时说明连接问题，按安装 SOP
提供 `--dcc-path` 和服务启动指引；不要把“配方存在”说成“已经能生成”。

## 生成与交付

生成图标的请求例子（用户已选择方案）：

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

`generate_asset` 返回 `prompt_id` 后，用工作流状态工具查询到终态，下载对应
文件并检查效果。批量生成受单次 4 张和总计 4 百万像素限制；种子用于复现。
提示词可描述画风、构图、照明、色板，但提示词不能保证透明通道或无缝纹理。

将图片交给下一步时先下载，再用 `upload_image` 上传到 ComfyUI input，并将
返回的 `subfolder/name`（无子目录时为 `name`） 传给 `parameters.image`。不要直接把输出 URL 塞给 LoadImage。
去背景选择 `birefnet-cutout`；3D 选择 `pixal3d-pbr` 或 `trellis2-pbr`，例如：

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

参考图宜为完整、居中的单个物体；Pixal3D 使用 MoGe 估计视角。减面数量是
目标而非保证。下载 GLB 后检查面数、孔洞、UV、材质、朝向和尺度，再交给
Blender/Godot/Unreal 等对应 MCP；碰撞、LOD、骨骼、动画和引擎导入需要另做。

OOM 时报告当前 prompt 的终态，提出单张、较小分辨率、较小纹理、其他模型
或 ComfyUI 官方卸载配置作为候选。切换方案需要用户选择；不盲目重试，
不清空整个队列，也不全局中断其他任务。

## 来源与许可边界

- [ComfyUI 官方工作流](https://github.com/Comfy-Org/workflow_templates)：配方记录固定提交，API 图经过裁剪，移除了 UI 子图、预览和无关分支。
- [FLUX.2 Klein 4B](https://huggingface.co/black-forest-labs/FLUX.2-klein-4B)：4B Apache 2.0；9B 和 base 不可直接替换当前 distilled 配方。
- [Z-Image Turbo](https://huggingface.co/Tongyi-MAI/Z-Image-Turbo)、[Qwen-Image 2512](https://huggingface.co/Qwen/Qwen-Image-2512)：模型卡列出 Apache 2.0。
- [SDXL](https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0)、[SD1.5 社区镜像](https://huggingface.co/stable-diffusion-v1-5/stable-diffusion-v1-5)：OpenRAIL 系列许可；镜像不是原厂仓库。
- [BiRefNet](https://huggingface.co/ZhengPeng7/BiRefNet)：MIT，使用 ComfyUI 原生权重包装。
- [Hunyuan3D 2 许可](https://huggingface.co/tencent/Hunyuan3D-2/blob/main/LICENSE)：有地域和使用条件；不是无条件免费商用。
- [TRELLIS.2](https://github.com/microsoft/TRELLIS.2)、[Pixal3D](https://github.com/TencentARC/Pixal3D)：主体 MIT，视觉编码器和其他依赖保留各自许可。

Hunyuan3D 2.1 的 PBR 自定义节点、Stable Fast 3D、第三方 TRELLIS2 包装器、
ControlNet/IP-Adapter/LoRA 也属于后续候选。当前已有通用工作流入口可承接
用户提供的 API 图，但这些方案未作为本批内置、验证过的配方。付费 Partner
Nodes 不属于本地免费生成路径。
