"""Run and verify the wooden-crate case through official ComfyUI HTTP APIs."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from dcc_mcp_comfyui.bridge import ComfyUIBridge, ComfyUIWorkflowError
from dcc_mcp_comfyui.game_assets import build_asset_workflow, prepare_asset_workflow

ROOT = Path(__file__).resolve().parent
CASE_PATH = ROOT / "case.json"
WORKFLOW_PATH = ROOT / "workflow_api.json"
RECEIPT_SCHEMA = "dcc-mcp-comfyui/example-receipt-v1"


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def workflow_sha256(workflow: dict[str, Any]) -> str:
    payload = json.dumps(workflow, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(payload)


def load_case() -> dict[str, Any]:
    value = json.loads(CASE_PATH.read_text(encoding="utf-8"))
    required = {"schema_version", "case_id", "recipe_id", "parameters", "models", "expected_workflow_sha256"}
    if not isinstance(value, dict) or value.keys() != required:
        raise ValueError("case.json must use the exact wooden-crate case schema")
    if value["schema_version"] != 1 or value["case_id"] != "wooden-crate-sd15-v1":
        raise ValueError("unsupported wooden-crate case version")
    return value


def materialize_workflow(case: dict[str, Any]) -> tuple[dict[str, Any], str]:
    built = build_asset_workflow(case["recipe_id"], case["parameters"], case["models"])
    workflow = built["workflow"]
    digest = workflow_sha256(workflow)
    if digest != built["provenance"]["workflow_sha256"]:
        raise ValueError("recipe provenance hash does not match canonical workflow")
    expected = case["expected_workflow_sha256"]
    if expected != "TO_BE_GENERATED" and digest != expected:
        raise ValueError(f"workflow drift: expected {expected}, got {digest}")
    return workflow, digest


def write_workflow() -> str:
    workflow, digest = materialize_workflow(load_case())
    WORKFLOW_PATH.write_bytes(canonical_bytes(workflow))
    return digest


def verify_workflow() -> str:
    workflow, digest = materialize_workflow(load_case())
    if not WORKFLOW_PATH.is_file():
        raise ValueError("workflow_api.json is stale; run the prepare command")
    committed_workflow = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))
    if canonical_bytes(committed_workflow) != canonical_bytes(workflow):
        raise ValueError("workflow_api.json is stale; run the prepare command")
    return digest


def receipt_body(receipt: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in receipt.items() if key != "receipt_sha256"}


def seal_receipt(body: dict[str, Any]) -> dict[str, Any]:
    return {**body, "receipt_sha256": sha256_bytes(canonical_bytes(body))}


def verify_receipt(path: Path) -> dict[str, Any]:
    receipt = json.loads(path.read_text(encoding="utf-8"))
    if receipt.get("schema") != RECEIPT_SCHEMA:
        raise ValueError("unsupported receipt schema")
    expected = sha256_bytes(canonical_bytes(receipt_body(receipt)))
    if receipt.get("receipt_sha256") != expected:
        raise ValueError("receipt checksum mismatch")
    output_root = path.parent.resolve()
    for artifact in receipt.get("artifacts", []):
        candidate = (output_root / artifact["local_name"]).resolve()
        if output_root not in candidate.parents or not candidate.is_file():
            raise ValueError(f"missing or unsafe artifact: {artifact.get('local_name')}")
        if candidate.stat().st_size != artifact["size_bytes"] or sha256_file(candidate) != artifact["sha256"]:
            raise ValueError(f"artifact evidence mismatch: {artifact['local_name']}")
    return receipt


def run_case(base_url: str, output_dir: Path, timeout: float) -> Path:
    case = load_case()
    workflow_digest = verify_workflow()
    bridge = ComfyUIBridge(base_url, timeout=30)
    bridge.connect()
    prepared = prepare_asset_workflow(bridge, case["recipe_id"], case["parameters"], case["models"])
    if prepared["provenance"]["workflow_sha256"] != workflow_digest:
        raise ValueError("live preflight changed the committed workflow")
    if not prepared["ready"]:
        raise ComfyUIWorkflowError(f"case is not ready: {json.dumps(prepared['blockers'], sort_keys=True)}")
    job = bridge.submit_workflow(prepared["workflow"])
    status = bridge.wait_for_prompt(job["prompt_id"], timeout=timeout)
    if status["status"] != "completed":
        raise ComfyUIWorkflowError(f"case did not complete: {status['status']}")
    artifacts = bridge.list_artifacts(job["prompt_id"])
    if not artifacts:
        raise ComfyUIWorkflowError("completed prompt returned no artifacts")

    output_dir.mkdir(parents=True, exist_ok=True)
    evidence = []
    for index, artifact in enumerate(artifacts, start=1):
        suffix = Path(artifact["filename"]).suffix.lower() or ".bin"
        destination = output_dir / f"artifact-{index:02d}{suffix}"
        bridge.download_artifact(
            job["prompt_id"],
            artifact["filename"],
            destination,
            subfolder=artifact["subfolder"],
            folder_type=artifact["type"],
        )
        evidence.append(
            {
                "local_name": destination.name,
                "sha256": sha256_file(destination),
                "size_bytes": destination.stat().st_size,
                "source": {
                    "filename": artifact["filename"],
                    "subfolder": artifact["subfolder"],
                    "type": artifact["type"],
                },
            }
        )
    body = {
        "schema": RECEIPT_SCHEMA,
        "case_id": case["case_id"],
        "workflow_sha256": workflow_digest,
        "prompt_id": job["prompt_id"],
        "status": "completed",
        "artifacts": evidence,
        "validation": "official ComfyUI /object_info, /prompt, /history and /view roundtrip",
    }
    receipt_path = output_dir / "receipt.json"
    receipt_path.write_bytes(canonical_bytes(seal_receipt(body)))
    verify_receipt(receipt_path)
    return receipt_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("prepare", help="rebuild the committed API workflow")
    subparsers.add_parser("check", help="verify the committed workflow and case hash")
    run_parser = subparsers.add_parser("run", help="submit, wait, download and write a receipt")
    run_parser.add_argument("--base-url", default="http://127.0.0.1:8188")
    run_parser.add_argument("--output-dir", type=Path, default=ROOT / "output")
    run_parser.add_argument("--timeout", type=float, default=600)
    verify_parser = subparsers.add_parser("verify", help="verify a receipt and every downloaded artifact")
    verify_parser.add_argument("receipt", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            print(write_workflow())
        elif args.command == "check":
            print(verify_workflow())
        elif args.command == "run":
            print(run_case(args.base_url, args.output_dir, args.timeout))
        else:
            print(json.dumps(verify_receipt(args.receipt), indent=2, sort_keys=True))
    except (ComfyUIWorkflowError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
