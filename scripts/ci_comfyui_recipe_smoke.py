"""Check all recipes against pinned real ComfyUI without downloading weights.

This checks host schemas and a model-free image roundtrip, not model inference.
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from PIL import Image

from dcc_mcp_comfyui.bridge import ComfyUIBridge
from dcc_mcp_comfyui.game_assets import list_asset_recipes, prepare_asset_workflow


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    args = parser.parse_args()
    bridge = ComfyUIBridge(args.base_url, timeout=30)
    bridge.connect()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        reference = root / "recipe-smoke.png"
        Image.new("RGB", (32, 32), (35, 70, 105)).save(reference)
        uploaded = bridge.upload_image(reference)
        for recipe in list_asset_recipes():
            parameters = {"prompt": "A wooden game chest"} if recipe["kind"] == "image" else {"image": uploaded["name"]}
            result = prepare_asset_workflow(bridge, recipe["id"], parameters)
            unexpected = [item for item in result["blockers"] if item["code"] != "missing_model"]
            assert not unexpected, (recipe["id"], unexpected)
            assert not result["ready"], "CI should not have inference weights installed"
            assert {item["model_slot"] for item in result["blockers"]} == set(recipe["models"])
            print(f"Host contracts passed: {recipe['id']}; expected missing weights: {len(result['blockers'])}")

        workflow = {
            "1": {"class_type": "LoadImage", "inputs": {"image": uploaded["name"]}},
            "2": {"class_type": "ImageInvert", "inputs": {"image": ["1", 0]}},
            "3": {"class_type": "SaveImage", "inputs": {"images": ["2", 0], "filename_prefix": "recipe-smoke"}},
        }
        assert bridge.validate_workflow(workflow)["valid"]
        job = bridge.submit_workflow(workflow)
        status = bridge.wait_for_prompt(job["prompt_id"], timeout=60)
        assert status["status"] == "completed", status
        artifact = bridge.list_artifacts(job["prompt_id"])[0]
        destination = root / "result.png"
        bridge.download_artifact(job["prompt_id"], artifact["filename"], destination, subfolder=artifact["subfolder"])
        with Image.open(destination) as image:
            assert image.size == (32, 32)
            # ComfyUI saves float32 tensors by truncating to uint8. Inversion
            # can land just below an integer, yielding a one-level difference.
            for pixel in image.convert("RGB").getdata():
                assert all(abs(actual - expected) <= 1 for actual, expected in zip(pixel, (220, 185, 150))), pixel
        print("Real ComfyUI upload, queue, status and artifact roundtrip passed (no AI weights).")


if __name__ == "__main__":
    main()
