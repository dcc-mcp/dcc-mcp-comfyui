"""Release lock projection and consistency contract tests."""

from __future__ import annotations

import importlib.util
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from dcc_mcp_comfyui import install as install_lifecycle

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli as tomllib


REPO_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_ROOT_PACKAGE = "dcc-mcp-comfyui"
SCRIPT_PATH = REPO_ROOT / "scripts" / "ci" / "check_uv_lock.py"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
LOCK_SYNC_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release-please-lock-sync.yml"
VERSION_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "version-consistency.yml"


def _load_checker_module():
    spec = importlib.util.spec_from_file_location("check_uv_lock", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_version_files(
    root: Path,
    *,
    project_version: str,
    lock_version: str,
    package_name: str = EXPECTED_ROOT_PACKAGE,
    project_name: str = EXPECTED_ROOT_PACKAGE,
    lock_name: str = EXPECTED_ROOT_PACKAGE,
    extra_lock_package: str = "",
) -> None:
    (root / "release-please-config.json").write_text(
        json.dumps({"packages": {".": {"package-name": package_name}}}),
        encoding="utf-8",
    )
    (root / ".release-please-manifest.json").write_text(json.dumps({".": project_version}), encoding="utf-8")
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "{project_name}"\nversion = "{project_version}"\n',
        encoding="utf-8",
    )
    (root / "uv.lock").write_text(
        f'version = 1\n\n[[package]]\nname = "{lock_name}"\n'
        f'version = "{lock_version}"\nsource = {{ editable = "." }}\n{extra_lock_package}',
        encoding="utf-8",
    )


def _workflow_step_commands(workflow_text: str, *, job: str, step_name: str) -> list[str]:
    workflow = yaml.safe_load(workflow_text)
    assert isinstance(workflow, dict)
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict)
    selected_job = jobs.get(job)
    assert isinstance(selected_job, dict)
    steps = selected_job.get("steps")
    assert isinstance(steps, list)
    matches = [step for step in steps if isinstance(step, dict) and step.get("name") == step_name]
    assert len(matches) == 1
    run = matches[0].get("run")
    assert isinstance(run, str)
    return [line.strip() for line in run.splitlines() if line.strip() and not line.lstrip().startswith("#")]


def _workflow_pull_request_paths(workflow_text: str) -> set[str]:
    workflow = yaml.safe_load(workflow_text)
    assert isinstance(workflow, dict)
    trigger = workflow.get("on", workflow.get(True))
    assert isinstance(trigger, dict)
    pull_request = trigger.get("pull_request")
    assert isinstance(pull_request, dict)
    paths = pull_request.get("paths")
    assert isinstance(paths, list)
    assert all(isinstance(path, str) for path in paths)
    return set(paths)


def test_stale_editable_root_version_is_rejected(tmp_path: Path) -> None:
    checker = _load_checker_module()
    _write_version_files(tmp_path, project_version="0.1.2", lock_version="0.1.1")

    errors = checker.check_uv_lock_consistency(tmp_path)

    assert errors == ["uv.lock editable root dcc-mcp-comfyui version '0.1.1' != expected '0.1.2'"]


def test_matching_editable_root_version_is_accepted(tmp_path: Path) -> None:
    checker = _load_checker_module()
    _write_version_files(tmp_path, project_version="0.1.2", lock_version="0.1.2")

    assert checker.check_uv_lock_consistency(tmp_path) == []


def test_synchronized_root_package_rename_is_rejected(tmp_path: Path) -> None:
    checker = _load_checker_module()
    _write_version_files(
        tmp_path,
        project_version="0.1.2",
        lock_version="0.1.2",
        package_name="renamed-adapter",
        project_name="renamed-adapter",
        lock_name="renamed-adapter",
    )

    assert checker.check_uv_lock_consistency(tmp_path) == [
        "release-please-config.json root package-name 'renamed-adapter' != fixed identity 'dcc-mcp-comfyui'"
    ]


def test_second_editable_shadow_root_is_rejected(tmp_path: Path) -> None:
    checker = _load_checker_module()
    _write_version_files(
        tmp_path,
        project_version="0.1.2",
        lock_version="0.1.2",
        extra_lock_package=('\n[[package]]\nname = "shadow-root"\nversion = "0.1.2"\nsource = { editable = "." }\n'),
    )

    assert checker.check_uv_lock_consistency(tmp_path) == [
        "uv.lock must contain exactly one source mapping with an editable key; found 2"
    ]


def test_noncanonical_second_editable_shadow_root_is_rejected(tmp_path: Path) -> None:
    checker = _load_checker_module()
    _write_version_files(
        tmp_path,
        project_version="0.1.2",
        lock_version="0.1.2",
        extra_lock_package=('\n[[package]]\nname = "shadow-root"\nversion = "0.1.2"\nsource = { editable = "./" }\n'),
    )

    assert checker.check_uv_lock_consistency(tmp_path) == [
        "uv.lock must contain exactly one source mapping with an editable key; found 2"
    ]


def test_noncanonical_only_editable_root_path_is_rejected(tmp_path: Path) -> None:
    checker = _load_checker_module()
    _write_version_files(tmp_path, project_version="0.1.2", lock_version="0.1.2")
    lock_path = tmp_path / "uv.lock"
    lock_path.write_text(
        lock_path.read_text(encoding="utf-8").replace('editable = "."', 'editable = "./"'),
        encoding="utf-8",
    )

    assert checker.check_uv_lock_consistency(tmp_path) == ["uv.lock editable root path './' != canonical '.'"]


def test_invalid_project_version_is_rejected(tmp_path: Path) -> None:
    checker = _load_checker_module()
    _write_version_files(tmp_path, project_version="latest", lock_version="latest")

    assert checker.check_uv_lock_consistency(tmp_path) == [
        ".release-please-manifest.json root version 'latest' is not a valid project version"
    ]


def test_uv_lock_symlink_is_rejected_even_when_bytes_match(tmp_path: Path) -> None:
    checker = _load_checker_module()
    _write_version_files(tmp_path, project_version="0.1.2", lock_version="0.1.2")
    lock_path = tmp_path / "uv.lock"
    target_path = tmp_path / "uv.lock.target"
    lock_path.replace(target_path)
    try:
        lock_path.symlink_to(target_path.name)
    except OSError as error:  # pragma: no cover - Windows without symlink capability
        pytest.skip(f"symlink capability unavailable: {error}")

    assert checker.check_uv_lock_consistency(tmp_path) == [
        "uv.lock must be a regular file and not a symlink or reparse point"
    ]


def test_uv_lock_directory_is_rejected_as_non_regular(tmp_path: Path) -> None:
    checker = _load_checker_module()
    _write_version_files(tmp_path, project_version="0.1.2", lock_version="0.1.2")
    lock_path = tmp_path / "uv.lock"
    lock_path.unlink()
    lock_path.mkdir()

    assert checker.check_uv_lock_consistency(tmp_path) == [
        "uv.lock must be a regular file and not a symlink or reparse point"
    ]


@pytest.mark.parametrize(
    ("path", "content", "expected"),
    [
        (
            ".release-please-manifest.json",
            "[]",
            ".release-please-manifest.json must contain a JSON object",
        ),
        (
            "release-please-config.json",
            '{"packages": []}',
            "release-please-config.json packages must be a mapping",
        ),
        (
            "pyproject.toml",
            'project = "invalid"\n',
            "pyproject.toml project must be a mapping",
        ),
        (
            "uv.lock",
            'version = 1\npackage = "invalid"\n',
            "uv.lock package must be a list",
        ),
        (
            "uv.lock",
            'version = 1\npackage = ["invalid"]\n',
            "uv.lock package entries must be mappings",
        ),
    ],
)
def test_malformed_shapes_return_stable_errors(
    tmp_path: Path,
    path: str,
    content: str,
    expected: str,
) -> None:
    checker = _load_checker_module()
    _write_version_files(tmp_path, project_version="0.1.2", lock_version="0.1.2")
    (tmp_path / path).write_text(content, encoding="utf-8")

    assert checker.check_uv_lock_consistency(tmp_path) == [expected]


def test_release_workflows_regenerate_and_validate_uv_lock() -> None:
    sync_workflow = LOCK_SYNC_WORKFLOW.read_text(encoding="utf-8")
    version_workflow = VERSION_WORKFLOW.read_text(encoding="utf-8")

    sync_commands = _workflow_step_commands(
        sync_workflow,
        job="sync-uv-lock",
        step_name="Sync generated lock metadata",
    )
    assert sync_commands == ["vx uv lock", "python scripts/ci/check_uv_lock.py"]
    commit_commands = _workflow_step_commands(
        sync_workflow,
        job="sync-uv-lock",
        step_name="Commit and push changes",
    )
    assert "git add uv.lock" in commit_commands

    check_commands = _workflow_step_commands(
        version_workflow,
        job="version-consistency",
        step_name="Check uv lock consistency",
    )
    assert check_commands == ["python scripts/ci/check_uv_lock.py", "vx uv lock --check"]
    assert {
        "release-please-config.json",
        ".release-please-manifest.json",
        "pyproject.toml",
        "uv.lock",
        "scripts/ci/check_uv_lock.py",
        ".github/workflows/version-consistency.yml",
    }.issubset(_workflow_pull_request_paths(version_workflow))


def test_release_candidate_ci_assertion_uses_canonical_adapter_version(tmp_path: Path) -> None:
    """Execute the CI assertion with the next canonical release installed."""
    _write_version_files(tmp_path, project_version="0.1.3", lock_version="0.1.3")
    checker_path = tmp_path / "scripts" / "ci" / "check_uv_lock.py"
    checker_path.parent.mkdir(parents=True)
    shutil.copy2(SCRIPT_PATH, checker_path)
    sitecustomize_path = tmp_path / "sitecustomize.py"
    sitecustomize_path.write_text(
        "import importlib.metadata\n"
        "versions = {'dcc-mcp-core': '0.20.8', 'dcc-mcp-comfyui': '0.1.3'}\n"
        "importlib.metadata.version = versions.__getitem__\n",
        encoding="utf-8",
    )

    ci_workflow = CI_WORKFLOW.read_text(encoding="utf-8")
    assertion_commands = _workflow_step_commands(
        ci_workflow,
        job="test",
        step_name="Verify resolved dependency versions",
    )
    assert assertion_commands[0] == "python -m pip check"
    assert len(assertion_commands) == 2
    assertion_command = assertion_commands[1]
    command = shlex.split(assertion_command)
    assert command[0] == "python"
    environment = os.environ.copy()
    environment["EXPECTED_CORE"] = "0.20.8"
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(tmp_path), environment["PYTHONPATH"]] if environment.get("PYTHONPATH") else [str(tmp_path)]
    )

    completed = subprocess.run(
        [sys.executable, *command[1:]],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert assertion_command == "python scripts/ci/check_uv_lock.py --installed"

    sitecustomize_path.write_text(
        "import importlib.metadata\n"
        "versions = {'dcc-mcp-core': '0.20.8', 'dcc-mcp-comfyui': '0.1.2'}\n"
        "importlib.metadata.version = versions.__getitem__\n",
        encoding="utf-8",
    )
    shutil.rmtree(tmp_path / "__pycache__", ignore_errors=True)
    stale_install = subprocess.run(
        [sys.executable, *command[1:]],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert stale_install.returncode == 1
    assert "installed dcc-mcp-comfyui version '0.1.2' != expected '0.1.3'" in stale_install.stderr

    version_workflow = VERSION_WORKFLOW.read_text(encoding="utf-8")
    assert "python scripts/ci/check_uv_lock.py" in _workflow_step_commands(
        version_workflow,
        job="version-consistency",
        step_name="Check uv lock consistency",
    )
    assert ".github/workflows/ci.yml" in _workflow_pull_request_paths(version_workflow)


def test_comment_only_lock_command_is_not_executable() -> None:
    workflow = VERSION_WORKFLOW.read_text(encoding="utf-8").replace(
        "          vx uv lock --check",
        "          # vx uv lock --check",
        1,
    )

    commands = _workflow_step_commands(
        workflow,
        job="version-consistency",
        step_name="Check uv lock consistency",
    )

    assert commands == ["python scripts/ci/check_uv_lock.py"]


def test_checked_in_uv_lock_matches_release_version() -> None:
    manifest = json.loads((REPO_ROOT / ".release-please-manifest.json").read_text(encoding="utf-8"))
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads((REPO_ROOT / "uv.lock").read_text(encoding="utf-8"))
    editable_roots = [
        package
        for package in lock["package"]
        if isinstance(package.get("source"), dict) and "editable" in package["source"]
    ]

    assert manifest["."] == pyproject["project"]["version"]
    assert editable_roots == [
        {
            **editable_roots[0],
            "name": EXPECTED_ROOT_PACKAGE,
            "version": manifest["."],
        }
    ]
    assert editable_roots[0]["source"]["editable"] == "."


def test_core_floor_matches_runtime_docs_and_bundled_skills() -> None:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    expected_spec = "dcc-mcp-core>=0.20.8,<1.0.0"

    assert install_lifecycle.MIN_CORE_VERSION == "0.20.8"
    assert expected_spec in pyproject["project"]["dependencies"]
    install_guide = (REPO_ROOT / "install.md").read_text(encoding="utf-8")
    assert expected_spec in install_guide
    assert install_guide.count(">=0.20.8,<1.0.0") == 2
    for skill_path in sorted((REPO_ROOT / "src" / "dcc_mcp_comfyui" / "skills").glob("*/SKILL.md")):
        skill = skill_path.read_text(encoding="utf-8")
        assert expected_spec in skill
        assert "do not establish readiness of a live ComfyUI host" in " ".join(skill.split())
