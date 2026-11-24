"""Current repository entrypoints and the real main-push boundary."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "repo_guardrails", ROOT / "scripts/repo_guardrails.py",
)
assert spec and spec.loader
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def test_current_repository_entrypoints_exist():
    assert guard.check_policy(ROOT) == []


def test_missing_entrypoints_fail_without_requiring_task_ledgers(tmp_path):
    assert guard.main(["policy", "--repo-root", str(tmp_path)]) == 2
    for path in (
        ".github/workflows/ci.yml", ".github/pull_request_template.md",
        ".github/CODEOWNERS", ".githooks/pre-push", "scripts/install_git_hooks.ps1",
    ):
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch()
    assert guard.main(["policy", "--repo-root", str(tmp_path)]) == 0
    assert list(tmp_path.rglob("PROGRESS.jsonl")) == []


@pytest.mark.parametrize("remote_branch,allowed", [("dev", True), ("main", False)])
def test_real_pre_push_hook_protects_main(remote_branch, allowed):
    sha = "0" * 40
    result = subprocess.run(
        ["sh", str(ROOT / ".githooks/pre-push")],
        input=f"refs/heads/dev {sha} refs/heads/{remote_branch} {sha}\n",
        text=True, capture_output=True, check=False,
    )
    assert (result.returncode == 0) is allowed, result.stderr
