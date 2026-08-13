"""Exercise the asset-sync extension against a live ComfyUI process."""

from __future__ import annotations

import argparse
from pathlib import Path

import httpx

from dcc_mcp_comfyui.asset_sync import stage_3d_asset
from dcc_mcp_comfyui.bridge import ComfyUIBridge


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--input-root", type=Path, required=True)
    args = parser.parse_args()

    args.source_root.mkdir(parents=True, exist_ok=True)
    args.input_root.mkdir(parents=True, exist_ok=True)
    source = args.source_root / "ci-sphere.obj"
    source.write_text(
        "\n".join(
            (
                "o ci-sphere",
                "v 0.0 0.0 1.0",
                "v 1.0 0.0 0.0",
                "v 0.0 1.0 0.0",
                "f 1 2 3",
                "",
            )
        ),
        encoding="utf-8",
    )

    staged = stage_3d_asset(
        source_name=source.name,
        source_root=args.source_root,
        input_root=args.input_root,
        channel_id="ci-blender",
        asset_id="sphere",
        format="obj",
        mime="model/obj",
        expected_head_revision=0,
        source_instance_id="ci",
    )

    bridge = ComfyUIBridge(args.base_url, timeout=30.0)
    bridge.connect()
    assert "Load3D" in bridge.get_node_names()

    with httpx.Client(base_url=args.base_url, timeout=30.0) as client:
        latest = client.get(
            "/dcc-mcp-sync/latest",
            params={"channel_id": "ci-blender", "asset_id": "sphere"},
        )
        latest.raise_for_status()
        assert latest.json() == staged["latest"]

        extension = client.get("/extensions/dcc_mcp_sync/dcc_mcp_sync.js")
        extension.raise_for_status()
        assert "dcc-mcp-sync/latest" in extension.text

    staged_path = args.input_root / staged["input_name"]
    assert staged_path.is_file()
    assert staged_path.read_bytes() == source.read_bytes()
    print(f"ComfyUI asset-sync smoke passed: revision={staged['latest']['revision']} input={staged['input_name']}")


if __name__ == "__main__":
    main()
