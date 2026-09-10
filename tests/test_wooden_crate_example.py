from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
EXAMPLE = ROOT / "examples" / "wooden-crate"
SPEC = importlib.util.spec_from_file_location("wooden_crate_example", EXAMPLE / "run.py")
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def test_committed_wooden_crate_workflow_is_canonical_and_pinned() -> None:
    case = runner.load_case()
    workflow, digest = runner.materialize_workflow(case)

    assert digest == case["expected_workflow_sha256"]
    committed = json.loads((EXAMPLE / "workflow_api.json").read_text(encoding="utf-8"))
    assert runner.canonical_bytes(committed) == runner.canonical_bytes(workflow)
    assert workflow["7"]["inputs"]["seed"] == 174203
    assert workflow["9"]["inputs"]["filename_prefix"] == "examples/wooden-crate"
    assert {node["class_type"] for node in workflow.values()} == {
        "CheckpointLoaderSimple",
        "CLIPTextEncode",
        "EmptyLatentImage",
        "KSampler",
        "VAEDecode",
        "SaveImage",
    }


def test_receipt_verification_detects_artifact_tampering(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact-01.png"
    artifact.write_bytes(b"real artifact bytes")
    body = {
        "schema": runner.RECEIPT_SCHEMA,
        "case_id": "wooden-crate-sd15-v1",
        "workflow_sha256": "a" * 64,
        "prompt_id": "prompt-1",
        "status": "completed",
        "artifacts": [
            {
                "local_name": artifact.name,
                "sha256": runner.sha256_file(artifact),
                "size_bytes": artifact.stat().st_size,
                "source": {"filename": "crate.png", "subfolder": "examples", "type": "output"},
            }
        ],
        "validation": "fixture",
    }
    receipt = tmp_path / "receipt.json"
    receipt.write_bytes(runner.canonical_bytes(runner.seal_receipt(body)))
    assert runner.verify_receipt(receipt)["case_id"] == "wooden-crate-sd15-v1"

    artifact.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="artifact evidence mismatch"):
        runner.verify_receipt(receipt)


def test_receipt_verification_rejects_path_escape(tmp_path: Path) -> None:
    body = {
        "schema": runner.RECEIPT_SCHEMA,
        "case_id": "wooden-crate-sd15-v1",
        "workflow_sha256": "a" * 64,
        "prompt_id": "prompt-1",
        "status": "completed",
        "artifacts": [{"local_name": "../escape.png", "sha256": "b" * 64, "size_bytes": 1, "source": {}}],
        "validation": "fixture",
    }
    receipt = tmp_path / "receipt.json"
    receipt.write_bytes(runner.canonical_bytes(runner.seal_receipt(body)))
    with pytest.raises(ValueError, match="missing or unsafe artifact"):
        runner.verify_receipt(receipt)


def test_case_schema_rejects_unreviewed_fields(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = json.loads((EXAMPLE / "case.json").read_text(encoding="utf-8"))
    case["download_model"] = True
    candidate = tmp_path / "case.json"
    candidate.write_text(json.dumps(case), encoding="utf-8")
    monkeypatch.setattr(runner, "CASE_PATH", candidate)
    with pytest.raises(ValueError, match="exact wooden-crate case schema"):
        runner.load_case()
