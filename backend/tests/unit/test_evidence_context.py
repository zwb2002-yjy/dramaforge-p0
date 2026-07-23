from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "scripts"))

from evidence_context import (  # noqa: E402
    begin_evidence_context,
    default_evidence_dir,
    evidence_source_errors,
    finish_evidence_context,
    require_ignored_evidence_path,
    sanitize_command,
)


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "evidence@example.com")
    _git(root, "config", "user.name", "Evidence Test")
    (root / "tracked.txt").write_text("clean\n", encoding="utf-8")
    (root / ".gitignore").write_text("tmp/\n", encoding="utf-8")
    _git(root, "add", "tracked.txt", ".gitignore")
    _git(root, "commit", "-m", "init")
    return root


def test_command_summary_redacts_sensitive_values() -> None:
    command = sanitize_command(
        [
            "prove.py",
            "--worker-token",
            "secret-value",
            "--api-key=also-secret",
            "password=inline-secret",
            "--base",
            "http://127.0.0.1:8010",
        ]
    )
    assert command == [
        "prove.py",
        "--worker-token",
        "[REDACTED]",
        "--api-key=[REDACTED]",
        "password=[REDACTED]",
        "--base",
        "http://127.0.0.1:8010",
    ]


def test_clean_source_context_is_commit_bound(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    context = begin_evidence_context(root, argv=["prove.py"])
    finished = finish_evidence_context(context, root)

    assert finished["source_commit"] == _git(root, "rev-parse", "HEAD")
    assert finished["dirty"] is False
    assert finished["ending_dirty"] is False
    assert finished["source_consistent"] is True
    assert evidence_source_errors(
        finished,
        expected_commit=finished["source_commit"],
    ) == []
    assert default_evidence_dir(root, finished["source_commit"], "formal") == (
        root / "tmp" / "p0-evidence" / finished["source_commit"] / "formal"
    )
    assert require_ignored_evidence_path(root, root / "tmp" / "report.json") == (
        root / "tmp" / "report.json"
    )


def test_source_change_invalidates_evidence(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    context = begin_evidence_context(root, argv=["prove.py"])
    (root / "tracked.txt").write_text("dirty\n", encoding="utf-8")
    finished = finish_evidence_context(context, root)

    assert finished["source_consistent"] is False
    assert "ending_dirty=True" in evidence_source_errors(
        finished,
        expected_commit=finished["source_commit"],
    )
