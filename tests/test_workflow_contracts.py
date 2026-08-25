"""Parsed workflow security, dependency, and release provenance contracts."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from yaml.resolver import BaseResolver

ROOT = Path(__file__).parents[1]
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
SHA = re.compile(r"^[0-9a-f]{40}$")
HEAD_SOURCE_BINDING = 'test "$(git rev-parse HEAD)" = "$source_sha"'
GH_UPLOAD_COMMAND = 'gh release upload "$TAG" dist/*.whl dist/*.tar.gz --repo "$GITHUB_REPOSITORY"'
ARTIFACT_METADATA_COMMAND = 'artifact_metadata="$(gh api "repos/$GITHUB_REPOSITORY/actions/artifacts/$ARTIFACT_ID")"'
ARTIFACT_ARCHIVE_COMMAND = 'gh api "repos/$GITHUB_REPOSITORY/actions/artifacts/$ARTIFACT_ID/zip" > "$artifact_archive"'
ARTIFACT_DIGEST_COMMAND = 'test "$(sha256sum "$artifact_archive" | cut -d\' \' -f1)" = "$expected_artifact_digest"'
ARTIFACT_ID_COMMAND = 'test "$(jq -r \'.id // empty\' <<< "$artifact_metadata")" = "$ARTIFACT_ID"'
ARTIFACT_METADATA_DIGEST_COMMAND = 'test "$(jq -r \'.digest // empty\' <<< "$artifact_metadata")" = "$ARTIFACT_DIGEST"'
ARTIFACT_HEAD_COMMAND = 'test "$(jq -r \'.workflow_run.head_sha // empty\' <<< "$artifact_metadata")" = "$SOURCE_SHA"'
ARTIFACT_URL_COMMAND = (
    'test "$(jq -r \'.archive_download_url // empty\' <<< "$artifact_metadata")" = '
    '"https://api.github.com/repos/$GITHUB_REPOSITORY/actions/artifacts/$ARTIFACT_ID/zip"'
)

PINNED_ACTIONS = {
    "googleapis/release-please-action": "45996ed1f6d02564a971a2fa1b5860e934307cf7",
    "actions/checkout": "d23441a48e516b6c34aea4fa41551a30e30af803",
    "actions/setup-python": "ece7cb06caefa5fff74198d8649806c4678c61a1",
    "actions/upload-artifact": "ea165f8d65b6e75b540449e92b4886f43607fa02",
    "actions/download-artifact": "d3f86a106a0bac45b974a628896c90dbdf5c8093",
    "pypa/gh-action-pypi-publish": "dc37677b2e1c63e2034f94d8a5b11f265b73ba33",
}


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(loader, node, deep=False):
    mapping = {}
    for key, value in loader.construct_pairs(node, deep=deep):
        if key in mapping:
            raise AssertionError(f"duplicate YAML mapping key: {key}")
        mapping[key] = value
    return mapping


_UniqueKeyLoader.add_constructor(BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping)


def _load_workflow(text: str) -> dict:
    workflow = yaml.load(text, Loader=_UniqueKeyLoader)
    assert isinstance(workflow, dict)
    return workflow


def _steps(job: dict) -> list[dict]:
    return [step for step in job["steps"] if isinstance(step, dict)]


def _step(job: dict, name: str) -> tuple[int, dict]:
    matches = [(index, step) for index, step in enumerate(_steps(job)) if step.get("name") == name]
    assert len(matches) == 1, f"expected exactly one structured step: {name}"
    return matches[0]


def _run_lines(step: dict) -> list[str]:
    run = step.get("run")
    assert isinstance(run, str)
    return [line.strip() for line in run.splitlines() if line.strip() and not line.lstrip().startswith("#")]


def _assert_unique_steps(job_name: str, job: dict) -> None:
    names = [step["name"] for step in _steps(job) if "name" in step]
    ids = [step["id"] for step in _steps(job) if "id" in step]
    assert len(names) == len(set(names)), f"duplicate step name in {job_name}"
    assert len(ids) == len(set(ids)), f"duplicate step id in {job_name}"


def _assert_pinned_actions(jobs: dict) -> None:
    for job in jobs.values():
        for step in _steps(job):
            uses = step.get("uses")
            if not uses:
                continue
            owner, value = uses.split("@", 1)
            assert SHA.fullmatch(value), uses
            assert value == PINNED_ACTIONS[owner], uses


def _validate_ci_contract(text: str) -> None:
    workflow = _load_workflow(text)
    assert workflow["permissions"] == {}
    jobs = workflow["jobs"]
    assert all(1 <= job["timeout-minutes"] <= 30 for job in jobs.values())
    for name, job in jobs.items():
        _assert_unique_steps(name, job)
    _assert_pinned_actions(jobs)

    assert "--no-deps" not in text
    assert "DCC_MCP_CORE_REF" not in text
    assert "repository: dcc-mcp/dcc-mcp-core" not in text

    test_job = jobs["test"]
    include = test_job["strategy"]["matrix"]["include"]
    assert {entry["core-version"] for entry in include} == {"0.20.8", "0.20.19"}
    _, install = _step(test_job, "Install resolved adapter and Core")
    assert 'python -m pip install -e ".[dev]" "dcc-mcp-core==${{ matrix.core-version }}"' in install["run"]
    _, verify = _step(test_job, "Verify resolved dependency versions")
    assert "python -m pip check" in verify["run"]
    assert "matrix.core-version" in verify["env"]["EXPECTED_CORE"]
    assert "importlib.metadata.version" in verify["run"]

    lint_job = jobs["lint-and-build"]
    _, skill_lint = _step(lint_job, "Validate bundled Skills")
    assert skill_lint["run"] == "python scripts/ci/lint_skills.py"
    lint_runs = "\n".join(step.get("run", "") for step in _steps(lint_job))
    assert 'python -m pip install -e ".[dev]" "dcc-mcp-core==0.20.19"' in lint_runs
    assert "python -m pip check" in lint_runs

    integration = jobs["comfyui-integration"]
    _, integration_install = _step(integration, "Install ComfyUI and resolved adapter contracts")
    assert 'python -m pip install -e . "dcc-mcp-core==0.20.19"' in integration_install["run"]
    assert "python -m pip check" in integration_install["run"]


def _validate_release_contract(text: str) -> None:
    workflow = _load_workflow(text)
    trigger = workflow.get("on", workflow.get(True))
    assert isinstance(trigger, dict)
    assert trigger.get("workflow_dispatch") is None
    assert workflow["permissions"] == {}
    jobs = workflow["jobs"]
    assert set(jobs) == {"release-please", "build-release-artifact", "publish-pypi", "attach-github-release"}
    assert all(1 <= job["timeout-minutes"] <= 30 for job in jobs.values())
    for job_name, job in jobs.items():
        _assert_unique_steps(job_name, job)
    _assert_pinned_actions(jobs)

    build = jobs["build-release-artifact"]
    assert set(build["needs"]) == {"release-please"}
    assert build["permissions"] == {"contents": "read"}
    source_index, source = _step(build, "Capture immutable source identity")
    target_index, target = _step(build, "Verify Release target before build")
    build_index, _ = _step(build, "Build exact release distributions")
    upload_index, upload = _step(build, "Upload immutable release artifact")
    assert source["run"].count(HEAD_SOURCE_BINDING) == 1
    assert "git fetch --force --no-tags" in source["run"]
    assert "target_commitish" in target["run"]
    assert "SOURCE_SHA" in target["run"]
    assert source_index < target_index < build_index < upload_index
    assert upload["uses"] == "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02"
    assert upload["with"]["path"] == "dist/*"
    assert upload["with"]["if-no-files-found"] == "error"
    assert upload["with"]["overwrite"] is False
    assert build["outputs"] == {
        "source_sha": "${{ steps.source.outputs.sha }}",
        "artifact_id": "${{ steps.upload.outputs.artifact-id }}",
        "artifact_digest": "${{ steps.upload.outputs.artifact-digest }}",
    }

    all_runs = "\n".join(step.get("run", "") for job in jobs.values() for step in _steps(job))
    assert all_runs.count("python -m build") == 1
    assert all_runs.count("gh release upload") == 1
    assert all_runs.count("sha256sum --check dist/SHA256SUMS") == 2
    assert "sha256sum dist/* > dist/SHA256SUMS" in all_runs
    assert "--clobber" not in all_runs

    for job_name in ("publish-pypi", "attach-github-release"):
        job = jobs[job_name]
        assert set(job["needs"]) == {"release-please", "build-release-artifact"}
        _, download = _step(job, "Download immutable release artifact")
        assert download["uses"] == "actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093"
        assert download["with"]["artifact-ids"] == "${{ needs.build-release-artifact.outputs.artifact_id }}"
        assert download["with"]["path"] == "dist"

    publish = jobs["publish-pypi"]
    assert publish["permissions"] == {"actions": "read", "contents": "read", "id-token": "write"}
    assert [step.get("name") for step in _steps(publish)] == [
        "Check out immutable source",
        "Download immutable release artifact",
        "Revalidate release immediately before PyPI",
        "Publish exact artifact to PyPI",
    ]
    verify_pypi_index, verify_pypi = _step(publish, "Revalidate release immediately before PyPI")
    assert _run_lines(verify_pypi)[-1] == "rm dist/SHA256SUMS"
    assert _steps(publish)[verify_pypi_index + 1]["uses"] == (
        "pypa/gh-action-pypi-publish@dc37677b2e1c63e2034f94d8a5b11f265b73ba33"
    )
    assert _steps(publish)[verify_pypi_index + 1]["with"]["packages-dir"] == "dist/"

    attach = jobs["attach-github-release"]
    assert attach["permissions"] == {"actions": "read", "contents": "write"}
    assert [step.get("name") for step in _steps(attach)] == [
        "Check out immutable source",
        "Download immutable release artifact",
        "Revalidate release immediately before GitHub upload",
        "Attach exact release artifacts without clobber",
    ]
    verify_gh_index, verify_gh = _step(attach, "Revalidate release immediately before GitHub upload")
    assert _run_lines(verify_gh)[-1] == "rm dist/SHA256SUMS"
    mutation = _steps(attach)[verify_gh_index + 1]
    assert mutation["name"] == "Attach exact release artifacts without clobber"
    assert mutation["run"] == GH_UPLOAD_COMMAND

    for verify in (verify_pypi, verify_gh):
        assert verify["env"]["ARTIFACT_ID"] == "${{ needs.build-release-artifact.outputs.artifact_id }}"
        assert verify["env"]["ARTIFACT_DIGEST"] == "${{ needs.build-release-artifact.outputs.artifact_digest }}"
        for required in (
            "gh api",
            "git fetch",
            "git rev-parse",
            "SOURCE_SHA",
            "ARTIFACT_ID",
            "ARTIFACT_DIGEST",
            "target_commitish",
            "sha256sum --check dist/SHA256SUMS",
            'test "${#wheels[@]}" -eq 1',
            'test "${#sdists[@]}" -eq 1',
            'test "${#files[@]}" -eq 3',
        ):
            assert required in verify["run"]
        lines = _run_lines(verify)
        assert ARTIFACT_METADATA_COMMAND in lines
        assert ARTIFACT_ID_COMMAND in lines
        assert ARTIFACT_METADATA_DIGEST_COMMAND in lines
        assert ARTIFACT_HEAD_COMMAND in lines
        assert ARTIFACT_URL_COMMAND in lines
        assert ARTIFACT_ARCHIVE_COMMAND in lines
        assert ARTIFACT_DIGEST_COMMAND in lines


def test_ci_uses_real_floor_and_latest_dependency_resolution() -> None:
    _validate_ci_contract(CI_WORKFLOW.read_text(encoding="utf-8"))


def test_release_builds_once_and_reuses_one_identity_bound_artifact() -> None:
    _validate_release_contract(RELEASE_WORKFLOW.read_text(encoding="utf-8"))


def test_release_contract_ignores_adversarial_comment_and_decoy_text() -> None:
    text = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    tampered = text.replace("python -m build", "python -m pip --version", 1)
    tampered += (
        "\n# python -m build\n# gh release upload dist/*\n# SOURCE_SHA ARTIFACT_ID ARTIFACT_DIGEST target_commitish\n"
    )

    with pytest.raises(AssertionError):
        _validate_release_contract(tampered)


def test_release_source_binding_ignores_comment_decoy() -> None:
    text = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    tampered = text.replace(f"          {HEAD_SOURCE_BINDING}\n", "", 1)
    tampered += f"\n# {HEAD_SOURCE_BINDING}\n"

    with pytest.raises(AssertionError):
        _validate_release_contract(tampered)


def test_release_contract_rejects_duplicate_mapping_key() -> None:
    text = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    tampered = text.replace("jobs:\n", "jobs:\n  release-please: {}\n", 1)

    with pytest.raises(AssertionError):
        _validate_release_contract(tampered)


def test_release_contract_rejects_duplicate_and_unbound_upload_mutations() -> None:
    text = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    marker = "      - name: Attach exact release artifacts without clobber\n"
    duplicate = "      - name: Attach exact release artifacts without clobber\n        run: echo duplicate\n"
    unbound = '      - name: Shadow release mutation\n        run: gh release upload "$TAG" dist/* --clobber\n'

    with pytest.raises(AssertionError):
        _validate_release_contract(text.replace(marker, duplicate + marker, 1))
    with pytest.raises(AssertionError):
        _validate_release_contract(text.replace(marker, unbound + marker, 1))


def test_release_contract_rejects_indirect_clobber_and_extra_upload_commands() -> None:
    text = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    indirect_clobber = (
        "run: |\n"
        "          flags=(--clo bber)\n"
        '          gh release upload "$TAG" dist/*.whl dist/*.tar.gz "${flags[@]}" '
        '--repo "$GITHUB_REPOSITORY"'
    )
    extra_command = "run: |\n          " + GH_UPLOAD_COMMAND + "\n          echo tamper"

    with pytest.raises(AssertionError):
        _validate_release_contract(text.replace("run: " + GH_UPLOAD_COMMAND, indirect_clobber, 1))
    with pytest.raises(AssertionError):
        _validate_release_contract(text.replace("run: " + GH_UPLOAD_COMMAND, extra_command, 1))


def test_release_contract_rejects_post_verify_steps_and_nonfinal_sidecar_removal() -> None:
    text = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    post_verify_step = "      - name: Post-publish tamper\n        run: echo tamper\n"
    marker = "  attach-github-release:\n"
    gh_without_final_removal = "          true".join(text.rsplit("          rm dist/SHA256SUMS", 1))

    with pytest.raises(AssertionError):
        _validate_release_contract(text.replace(marker, post_verify_step + marker, 1))
    with pytest.raises(AssertionError):
        _validate_release_contract(text.replace("          rm dist/SHA256SUMS", "          true", 1))
    with pytest.raises(AssertionError):
        _validate_release_contract(gh_without_final_removal)


def test_release_contract_rejects_unbound_artifact_digest_checks() -> None:
    text = RELEASE_WORKFLOW.read_text(encoding="utf-8")

    with pytest.raises(AssertionError):
        _validate_release_contract(
            text.replace(ARTIFACT_ARCHIVE_COMMAND, ARTIFACT_ARCHIVE_COMMAND.replace("$ARTIFACT_ID", "123"), 1)
        )
    with pytest.raises(AssertionError):
        _validate_release_contract(text.replace(ARTIFACT_DIGEST_COMMAND, "echo digest-not-checked", 1))
    with pytest.raises(AssertionError):
        _validate_release_contract(text.replace(ARTIFACT_ID_COMMAND, "true", 1))
    with pytest.raises(AssertionError):
        _validate_release_contract(text.replace(ARTIFACT_METADATA_DIGEST_COMMAND, "true", 1))


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=True)
    return result.stdout.strip()


def _bash_executable() -> str:
    git = shutil.which("git")
    assert git is not None
    if os.name == "nt":
        candidate = Path(git).resolve().parent.parent / "bin" / "bash.exe"
        if candidate.is_file():
            return str(candidate)
    bash = shutil.which("bash")
    assert bash is not None
    return bash


def test_release_source_capture_rejects_tag_move_after_checkout(tmp_path: Path) -> None:
    workflow = _load_workflow(RELEASE_WORKFLOW.read_text(encoding="utf-8"))
    _, source_step = _step(workflow["jobs"]["build-release-artifact"], "Capture immutable source identity")
    script = source_step["run"]

    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    checkout = tmp_path / "checkout"
    _git(tmp_path, "init", "--bare", str(remote))
    seed.mkdir()
    _git(seed, "init", "--initial-branch=main")
    _git(seed, "config", "user.name", "Release Contract")
    _git(seed, "config", "user.email", "release-contract@example.invalid")
    (seed / "payload.txt").write_text("A", encoding="utf-8")
    _git(seed, "add", "payload.txt")
    _git(seed, "commit", "-m", "A")
    commit_a = _git(seed, "rev-parse", "HEAD")
    _git(seed, "tag", "v0.1.2")
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "origin", "main", "refs/tags/v0.1.2")
    _git(tmp_path, "clone", str(remote), str(checkout))
    _git(checkout, "checkout", "--detach", "v0.1.2")

    environment = os.environ.copy()
    environment.update({"TAG": "v0.1.2", "GITHUB_OUTPUT": "source.out"})
    stable = subprocess.run(
        [_bash_executable(), "--noprofile", "--norc", "-euo", "pipefail", "-c", script],
        cwd=checkout,
        env=environment,
        text=True,
        capture_output=True,
    )
    assert stable.returncode == 0, stable.stderr
    assert f"sha={commit_a}" in (checkout / "source.out").read_text(encoding="utf-8")

    (seed / "payload.txt").write_text("B", encoding="utf-8")
    _git(seed, "commit", "-am", "B")
    _git(seed, "tag", "--force", "v0.1.2")
    _git(seed, "push", "--force", "origin", "refs/tags/v0.1.2")

    moved = subprocess.run(
        [_bash_executable(), "--noprofile", "--norc", "-euo", "pipefail", "-c", script],
        cwd=checkout,
        env=environment,
        text=True,
        capture_output=True,
    )
    assert moved.returncode != 0, "moved release tag must fail before build"
