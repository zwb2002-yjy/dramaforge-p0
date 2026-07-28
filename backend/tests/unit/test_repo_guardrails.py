from __future__ import annotations

import base64
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "scripts"))

import repo_guardrails  # noqa: E402
from repo_guardrails import (  # noqa: E402
    REQUIRED_CHECKS,
    GuardrailError,
    decode_event_payload,
    find_ownership_conflicts,
    normalize_owned_path,
    normalize_task_id,
    paths_overlap,
    read_events,
    validate_event,
    validate_worktree,
)


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc.stdout.strip()


def _make_task_worktree(tmp_path: Path, task_id: str) -> tuple[Path, Path]:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "guardrail@example.com")
    _git(root, "config", "user.name", "Guardrail Test")
    (root / "README.md").write_text("test\n", encoding="utf-8")
    (root / ".gitignore").write_text("/.worktrees/\n", encoding="utf-8")
    _git(root, "add", "README.md", ".gitignore")
    _git(root, "commit", "-m", "init")
    _git(root, "update-ref", "refs/remotes/origin/main", "main")
    _git(root, "branch", "dev", "main")
    _git(root, "update-ref", "refs/remotes/origin/dev", "dev")
    _git(root, "switch", "dev")
    worktree = root / ".worktrees" / task_id
    worktree.parent.mkdir()
    _git(root, "worktree", "add", str(worktree), "-b", f"agent/{task_id}", "dev")
    return root, worktree


def _write_started_event(
    progress: Path,
    *,
    task_id: str,
    owned_paths: list[str],
) -> None:
    progress.write_text(
        json.dumps(
            {
                "task_id": task_id,
                "status": "STARTED",
                "branch": f"agent/{task_id}",
                "worktree": f".worktrees/{task_id}",
                "owned_paths": owned_paths,
                "read_only": False,
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _commit_file(worktree: Path, relative_path: str, content: str = "change\n") -> str:
    path = worktree / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    _git(worktree, "add", relative_path)
    _git(worktree, "commit", "-m", f"change {relative_path}")
    return _git(worktree, "rev-parse", "HEAD")


def _prepare_merged_task(
    tmp_path: Path,
    *,
    task_id: str = "guard-test",
) -> tuple[Path, Path, str, str]:
    root, worktree = _make_task_worktree(tmp_path, task_id)
    task_commit = _commit_file(worktree, "backend/change.py")
    _git(root, "merge", "--no-ff", f"agent/{task_id}", "-m", "merge task")
    merge_commit = _git(root, "rev-parse", "HEAD")
    _git(root, "branch", "-f", "main", "dev")
    _git(root, "update-ref", "refs/remotes/origin/main", "main")
    progress = tmp_path / "PROGRESS.jsonl"
    progress.write_text(
        json.dumps(
            {
                "task_id": task_id,
                "status": "COMPLETED",
                "branch": f"agent/{task_id}",
                "worktree": f".worktrees/{task_id}",
                "owned_paths": ["backend"],
                "read_only": False,
                "commit": task_commit,
                "changed_files": ["backend/change.py"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return root, progress, task_commit, merge_commit


def _merged_pr_payload(
    *,
    task_id: str,
    task_commit: str,
    merge_commit: str,
) -> dict[str, object]:
    return {
        "number": 42,
        "state": "MERGED",
        "baseRefName": "main",
        "headRefName": "dev",
        "headRefOid": task_commit,
        "mergeCommit": {"oid": merge_commit},
        "mergedBy": {"login": "zwb2002-yjy"},
        "reviewDecision": "APPROVED",
        "reviews": [
            {
                "author": {"login": "zwb2002-yjy"},
                "state": "APPROVED",
                "submittedAt": "2026-07-22T00:00:00Z",
            }
        ],
        "statusCheckRollup": [
            {"name": check, "conclusion": "SUCCESS"} for check in REQUIRED_CHECKS
        ],
    }


def test_task_and_owned_path_normalization() -> None:
    assert normalize_task_id("REPO-GUARDRAILS") == "repo-guardrails"
    assert normalize_owned_path(r".\backend\app\\") == "backend/app"
    with pytest.raises(GuardrailError):
        normalize_task_id("bad task")
    with pytest.raises(GuardrailError):
        normalize_owned_path("../outside")
    with pytest.raises(GuardrailError):
        normalize_owned_path(".")


def test_base64_event_payload_preserves_windows_json_quotes() -> None:
    raw = json.dumps({"task_id": "guard-test", "status": "STARTED"})
    encoded = base64.b64encode(raw.encode("utf-8")).decode("ascii")
    assert decode_event_payload(event_json=None, event_base64=encoded) == {
        "task_id": "guard-test",
        "status": "STARTED",
    }


def test_progress_ledger_rejects_malformed_events(tmp_path: Path) -> None:
    progress = tmp_path / "PROGRESS.jsonl"
    progress.write_text(
        '{"task_id":"valid","status":"STARTED"}\nnot-json\n',
        encoding="utf-8",
    )

    with pytest.raises(GuardrailError, match=r"PROGRESS\.jsonl:2"):
        read_events(progress)


def test_directory_ownership_overlap_is_prefix_based() -> None:
    assert paths_overlap("backend", "backend/app/runtime")
    assert paths_overlap("scripts/repo_guardrails.py", "scripts/repo_guardrails.py")
    assert paths_overlap("Backend/App", "backend/app/runtime")
    assert not paths_overlap("backend/app", "backend/tests")


def test_active_read_only_task_does_not_claim_paths() -> None:
    events = [
        {
            "task_id": "reader",
            "status": "STARTED",
            "read_only": True,
            "owned_paths": ["backend"],
        },
        {
            "task_id": "writer",
            "status": "STARTED",
            "read_only": False,
            "owned_paths": ["frontend"],
        },
    ]
    assert find_ownership_conflicts(
        task_id="next",
        owned_paths=["backend/app"],
        events=events,
    ) == []
    assert find_ownership_conflicts(
        task_id="next",
        owned_paths=["frontend/src"],
        events=events,
    ) == ["frontend/src overlaps active task writer:frontend"]


def test_writable_started_event_requires_matching_branch_worktree_and_ownership(
    tmp_path: Path,
) -> None:
    root, worktree = _make_task_worktree(tmp_path, "guard-test")
    progress = root / ".agent-control" / "PROGRESS.jsonl"
    event = validate_event(
        repo_root=worktree,
        progress_path=progress,
        candidate={
            "task_id": "GUARD-TEST",
            "status": "STARTED",
            "owned_paths": ["backend/app"],
            "read_only": False,
        },
    )
    assert event["task_id"] == "guard-test"
    assert event["branch"] == "agent/guard-test"
    assert event["worktree"] == ".worktrees/guard-test"

    with pytest.raises(GuardrailError, match="nonempty owned paths"):
        validate_event(
            repo_root=worktree,
            progress_path=progress,
            candidate={
                "task_id": "guard-test",
                "status": "STARTED",
                "owned_paths": [],
                "read_only": False,
            },
        )


def test_daily_dev_task_uses_root_worktree(tmp_path: Path) -> None:
    root, _worktree = _make_task_worktree(tmp_path, "guard-test")
    progress = root / ".agent-control" / "PROGRESS.jsonl"

    event = validate_event(
        repo_root=root,
        progress_path=progress,
        candidate={
            "task_id": "daily-dev-task",
            "status": "STARTED",
            "owned_paths": ["backend/app"],
            "read_only": False,
        },
    )

    assert event["branch"] == "dev"
    assert event["worktree"] == "."


def test_writable_task_rejects_dirty_or_out_of_sync_root_dev(
    tmp_path: Path,
) -> None:
    root, worktree = _make_task_worktree(tmp_path, "guard-test")

    (root / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    with pytest.raises(GuardrailError, match="root dev worktree must stay clean"):
        validate_worktree(worktree, "guard-test")
    (root / "dirty.txt").unlink()

    _git(root, "update-ref", "refs/remotes/origin/dev", "dev^{}")
    (root / "README.md").write_text("changed\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "commit", "-m", "advance dev")
    with pytest.raises(GuardrailError, match="root dev must match origin/dev"):
        validate_worktree(worktree, "guard-test")


def test_follow_up_event_inherits_identity_and_rejects_drift(
    tmp_path: Path,
) -> None:
    root, worktree = _make_task_worktree(tmp_path, "guard-test")
    progress = tmp_path / "PROGRESS.jsonl"
    progress.write_text(
        json.dumps(
            {
                "task_id": "guard-test",
                "status": "STARTED",
                "branch": "agent/guard-test",
                "worktree": ".worktrees/guard-test",
                "owned_paths": ["backend"],
                "read_only": False,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    paused = validate_event(
        repo_root=worktree,
        progress_path=progress,
        candidate={"task_id": "guard-test", "status": "PAUSED"},
    )
    assert paused["owned_paths"] == ["backend"]
    assert paused["branch"] == "agent/guard-test"

    with pytest.raises(GuardrailError, match="owned_paths"):
        validate_event(
            repo_root=worktree,
            progress_path=progress,
            candidate={
                "task_id": "guard-test",
                "status": "PAUSED",
                "owned_paths": ["frontend"],
            },
        )

    with pytest.raises(GuardrailError, match="branch"):
        validate_event(
            repo_root=worktree,
            progress_path=progress,
            candidate={
                "task_id": "guard-test",
                "status": "PAUSED",
                "branch": "agent/other-task",
            },
        )


def test_event_lifecycle_rejects_unknown_status_and_invalid_transition(
    tmp_path: Path,
) -> None:
    root, worktree = _make_task_worktree(tmp_path, "guard-test")
    progress = tmp_path / "PROGRESS.jsonl"

    with pytest.raises(GuardrailError, match="unsupported status"):
        validate_event(
            repo_root=worktree,
            progress_path=progress,
            candidate={"task_id": "guard-test", "status": "RUNNING"},
        )
    with pytest.raises(GuardrailError, match="must start with STARTED"):
        validate_event(
            repo_root=worktree,
            progress_path=progress,
            candidate={"task_id": "guard-test", "status": "COMPLETED"},
        )

    progress.write_text(
        json.dumps(
            {
                "task_id": "guard-test",
                "status": "STARTED",
                "branch": "agent/guard-test",
                "worktree": ".worktrees/guard-test",
                "owned_paths": ["backend"],
                "read_only": False,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(GuardrailError, match="STARTED -> MERGED"):
        validate_event(
            repo_root=root,
            progress_path=progress,
            candidate={
                "task_id": "guard-test",
                "status": "MERGED",
                "approved_by": "@zwb2002-yjy",
            },
        )


def test_completed_rejects_dirty_uncommitted_worktree(tmp_path: Path) -> None:
    _root, worktree = _make_task_worktree(tmp_path, "guard-test")
    progress = tmp_path / "PROGRESS.jsonl"
    _write_started_event(
        progress,
        task_id="guard-test",
        owned_paths=["backend"],
    )
    dirty = worktree / "backend" / "dirty.py"
    dirty.parent.mkdir(parents=True)
    dirty.write_text("dirty\n", encoding="utf-8")

    with pytest.raises(GuardrailError, match="clean task worktree"):
        validate_event(
            repo_root=worktree,
            progress_path=progress,
            candidate={
                "task_id": "guard-test",
                "status": "COMPLETED",
                "commit": _git(worktree, "rev-parse", "HEAD"),
            },
        )


def test_completed_rejects_task_without_head_commit(tmp_path: Path) -> None:
    _root, worktree = _make_task_worktree(tmp_path, "guard-test")
    progress = tmp_path / "PROGRESS.jsonl"
    _write_started_event(
        progress,
        task_id="guard-test",
        owned_paths=["backend"],
    )

    with pytest.raises(GuardrailError, match="nonempty task HEAD commit"):
        validate_event(
            repo_root=worktree,
            progress_path=progress,
            candidate={
                "task_id": "guard-test",
                "status": "COMPLETED",
                "commit": _git(worktree, "rev-parse", "HEAD"),
            },
        )


def test_completed_requires_exact_declared_head_commit(tmp_path: Path) -> None:
    root, worktree = _make_task_worktree(tmp_path, "guard-test")
    progress = tmp_path / "PROGRESS.jsonl"
    _write_started_event(
        progress,
        task_id="guard-test",
        owned_paths=["backend"],
    )
    _commit_file(worktree, "backend/change.py")

    with pytest.raises(GuardrailError, match="exact task commit"):
        validate_event(
            repo_root=worktree,
            progress_path=progress,
            candidate={"task_id": "guard-test", "status": "COMPLETED"},
        )
    with pytest.raises(GuardrailError, match="must equal task HEAD"):
        validate_event(
            repo_root=worktree,
            progress_path=progress,
            candidate={
                "task_id": "guard-test",
                "status": "COMPLETED",
                "commit": _git(root, "rev-parse", "origin/main"),
            },
        )


def test_completed_rejects_committed_paths_outside_ownership(tmp_path: Path) -> None:
    _root, worktree = _make_task_worktree(tmp_path, "guard-test")
    progress = tmp_path / "PROGRESS.jsonl"
    _write_started_event(
        progress,
        task_id="guard-test",
        owned_paths=["backend"],
    )
    commit = _commit_file(worktree, "frontend/change.ts")

    with pytest.raises(GuardrailError, match="outside owned_paths"):
        validate_event(
            repo_root=worktree,
            progress_path=progress,
            candidate={
                "task_id": "guard-test",
                "status": "COMPLETED",
                "commit": commit,
            },
        )


def test_completed_accepts_clean_owned_committed_diff(tmp_path: Path) -> None:
    _root, worktree = _make_task_worktree(tmp_path, "guard-test")
    progress = tmp_path / "PROGRESS.jsonl"
    _write_started_event(
        progress,
        task_id="guard-test",
        owned_paths=["backend"],
    )
    commit = _commit_file(worktree, "backend/change.py")

    completed = validate_event(
        repo_root=worktree,
        progress_path=progress,
        candidate={
            "task_id": "guard-test",
            "status": "COMPLETED",
            "commit": commit,
        },
    )
    assert completed["commit"] == commit
    assert completed["changed_files"] == ["backend/change.py"]


def test_completed_accepts_utf8_owned_path(tmp_path: Path) -> None:
    _root, worktree = _make_task_worktree(tmp_path, "guard-test")
    progress = tmp_path / "PROGRESS.jsonl"
    _write_started_event(
        progress,
        task_id="guard-test",
        owned_paths=["docs"],
    )
    commit = _commit_file(worktree, "docs/开发执行检查点.md")

    completed = validate_event(
        repo_root=worktree,
        progress_path=progress,
        candidate={
            "task_id": "guard-test",
            "status": "COMPLETED",
            "commit": commit,
        },
    )
    assert completed["changed_files"] == ["docs/开发执行检查点.md"]


def test_merged_rejects_approval_text_without_positive_pr_number(
    tmp_path: Path,
) -> None:
    root, progress, _task_commit, _merge_commit = _prepare_merged_task(tmp_path)
    with pytest.raises(GuardrailError, match="positive GitHub pull request number"):
        validate_event(
            repo_root=root,
            progress_path=progress,
            candidate={
                "task_id": "guard-test",
                "status": "MERGED",
                "approved_by": "@zwb2002-yjy",
            },
        )


def test_merged_requires_verified_github_pr_facts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, progress, _task_commit, _merge_commit = _prepare_merged_task(tmp_path)
    monkeypatch.setattr(repo_guardrails, "_gh_json", lambda *_args: {})

    with pytest.raises(GuardrailError, match="is not merged"):
        validate_event(
            repo_root=root,
            progress_path=progress,
            candidate={
                "task_id": "guard-test",
                "status": "MERGED",
                "approved_by": "@zwb2002-yjy",
                "pr_number": 42,
            },
        )


def test_merged_accepts_release_pr_with_multiple_task_commits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, progress, task_commit, merge_commit = _prepare_merged_task(tmp_path)
    payload = _merged_pr_payload(
        task_id="guard-test",
        task_commit=task_commit,
        merge_commit=merge_commit,
    )
    payload["headRefOid"] = _git(root, "rev-parse", "main")
    monkeypatch.setattr(repo_guardrails, "_gh_json", lambda *_args: payload)

    merged = validate_event(
        repo_root=root,
        progress_path=progress,
        candidate={
            "task_id": "guard-test",
            "status": "MERGED",
            "approved_by": "@zwb2002-yjy",
            "pr_number": 42,
        },
    )
    assert merged["merge_commit"] == merge_commit


def test_merged_requires_all_successful_checks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, progress, task_commit, merge_commit = _prepare_merged_task(tmp_path)
    payload = _merged_pr_payload(
        task_id="guard-test",
        task_commit=task_commit,
        merge_commit=merge_commit,
    )
    payload["statusCheckRollup"] = [
        {"name": REQUIRED_CHECKS[0], "conclusion": "FAILURE"}
    ]
    monkeypatch.setattr(repo_guardrails, "_gh_json", lambda *_args: payload)

    with pytest.raises(GuardrailError, match="lacks successful required checks"):
        validate_event(
            repo_root=root,
            progress_path=progress,
            candidate={
                "task_id": "guard-test",
                "status": "MERGED",
                "approved_by": "@zwb2002-yjy",
                "pr_number": 42,
            },
        )


def test_merged_accepts_verified_approved_pr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, progress, task_commit, merge_commit = _prepare_merged_task(tmp_path)
    payload = _merged_pr_payload(
        task_id="guard-test",
        task_commit=task_commit,
        merge_commit=merge_commit,
    )
    monkeypatch.setattr(repo_guardrails, "_gh_json", lambda *_args: payload)

    merged = validate_event(
        repo_root=root,
        progress_path=progress,
        candidate={
            "task_id": "guard-test",
            "status": "MERGED",
            "approved_by": "@zwb2002-yjy",
            "pr_number": 42,
        },
    )
    assert merged["approved_by"] == "@zwb2002-yjy"
    assert merged["commit"] == merge_commit
    assert merged["merge_commit"] == merge_commit
