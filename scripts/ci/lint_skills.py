#!/usr/bin/env python3
"""Validate every bundled ComfyUI Skill with the Core contract validator."""

from pathlib import Path

from dcc_mcp_core import validate_skill

SKILLS_ROOT = Path(__file__).parents[2] / "src" / "dcc_mcp_comfyui" / "skills"


def main() -> None:
    skill_paths = sorted(path for path in SKILLS_ROOT.iterdir() if path.is_dir())
    reports = [validate_skill(str(path)) for path in skill_paths]
    failures = [report.issues for report in reports if not report.is_clean]
    if failures:
        raise SystemExit(str(failures))
    print(f"validated {len(reports)} bundled skills")


if __name__ == "__main__":
    main()
