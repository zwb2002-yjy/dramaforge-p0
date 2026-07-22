#!/usr/bin/env python3
"""Repository workflow guardrails shared by PowerShell helpers and CI."""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ACTIVE_STATUSES = {"STARTED", "PAUSED"}
ALLOWED_STATUSES = {"STARTED", "PAUSED", "COMPLETED", "FAILED", "MERGED"}
ALLOWED_TRANSITIONS: dict[str | None, set[str]] = {
    None: {"STARTED"},
    "STARTED": {"PAUSED", "COMPLETED", "FAILED"},
    "PAUSED": {"STARTED", "COMPLETED", "FAILED"},
    "COMPLETED": {"PAUSED", "FAILED", "MERGED"},
    "FAILED": set(),
    "MERGED": set(),
}
MERGE_APPROVER = "@zwb2002-yjy"
REQUIRED_CHECKS = (
    "policy",
    "backend-static",
    "backend-unit",
    "postgres-integration",
    "frontend",
    "frontend-smoke",
    "frontend-smoke-windows",
)
TASK_ID_RE = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")


class GuardrailError(ValueError):
    """Raised when a repository workflow invariant is violated."""


def normalize_task_id(value: str) -> str:
    task_id = value.strip().lower()
    if not TASK_ID_RE.fullmatch(task_id):
        raise GuardrailError(
            "task id must contain lowercase letters, numbers, dots, underscores, or hyphens"
        )
    return task_id


def normalize_owned_path(value: str) -> str:
    raw = value.strip().replace("\\", "/")
    while raw.startswith("./"):
        raw = raw[2:]
    raw = raw.rstrip("/")
    if not raw:
        raise GuardrailError("owned path must not be empty")
    path = Path(raw)
    if path.is_absolute() or ".." in path.parts:
        raise GuardrailError(f"owned path must be repository-relative: {value}")
    normalized = "/".join(part for part in path.parts if part not in {"", "."})
    if not normalized:
        raise GuardrailError("owned path must not resolve to the repository root")
    return normalized


def normalize_owned_paths(values: list[str]) -> list[str]:
    normalized: dict[str, str] = {}
    for value in values:
        if not value.strip():
            continue
        path = normalize_owned_path(value)
        normalized.setdefault(path.casefold(), path)
    return [normalized[key] for key in sorted(normalized)]


def paths_overlap(left: str, right: str) -> bool:
    left_parts = normalize_owned_path(left).casefold().split("/")
    right_parts = normalize_owned_path(right).casefold().split("/")
    common = min(len(left_parts), len(right_parts))
    return left_parts[:common] == right_parts[:common]


def path_is_owned(path: str, owned_path: str) -> bool:
    path_parts = normalize_owned_path(path).casefold().split("/")
    owned_parts = normalize_owned_path(owned_path).casefold().split("/")
    return len(path_parts) >= len(owned_parts) and path_parts[: len(owned_parts)] == owned_parts


def read_events(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise GuardrailError(
                f"invalid progress ledger JSON at {path}:{line_number}: {exc.msg}"
            ) from exc
        if not isinstance(event, dict):
            raise GuardrailError(
                f"progress ledger event must be an object at {path}:{line_number}"
            )
        events.append(event)
    return events


def decode_event_payload(
    *,
    event_json: str | None,
    event_base64: str | None,
) -> dict[str, Any]:
    raw = event_json
    if event_base64 is not None:
        try:
            raw = base64.b64decode(event_base64, validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError) as exc:
            raise GuardrailError("event Base64 must contain UTF-8 JSON") from exc
    if raw is None:
        raise GuardrailError("event payload is required")
    candidate = json.loads(raw)
    if not isinstance(candidate, dict):
        raise GuardrailError("event JSON must be an object")
    return candidate


def latest_events_by_task(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for event in events:
        raw_task_id = str(event.get("task_id") or "").strip()
        if not raw_task_id:
            continue
        try:
            task_id = normalize_task_id(raw_task_id)
        except GuardrailError:
            continue
        latest[task_id] = event
    return latest


def find_ownership_conflicts(
    *,
    task_id: str,
    owned_paths: list[str],
    events: list[dict[str, Any]],
) -> list[str]:
    conflicts: list[str] = []
    for other_task, event in latest_events_by_task(events).items():
        if other_task == task_id or event.get("status") not in ACTIVE_STATUSES:
            continue
        if bool(event.get("read_only")):
            continue
        other_paths = normalize_owned_paths(
            [str(value) for value in event.get("owned_paths") or []]
        )
        for owned_path in owned_paths:
            for other_path in other_paths:
                if paths_overlap(owned_path, other_path):
                    conflicts.append(
                        f"{owned_path} overlaps active task {other_task}:{other_path}"
                    )
    return conflicts


def _git(repo_root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise GuardrailError((proc.stderr or proc.stdout).strip() or "git command failed")
    return proc.stdout.strip()


def _git_succeeds(repo_root: Path, *args: str) -> bool:
    proc = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode not in {0, 1}:
        raise GuardrailError((proc.stderr or proc.stdout).strip() or "git command failed")
    return proc.returncode == 0


def _gh_json(repo_root: Path, *args: str) -> dict[str, Any] | list[dict[str, Any]]:
    try:
        proc = subprocess.run(
            ["gh", *args],
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as exc:
        raise GuardrailError(
            "GitHub CLI is required to verify MERGED and repository ruleset facts"
        ) from exc
    if proc.returncode != 0:
        raise GuardrailError(
            (proc.stderr or proc.stdout).strip() or "GitHub CLI command failed"
        )
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise GuardrailError("GitHub CLI returned invalid JSON") from exc
    if not isinstance(payload, dict | list):
        raise GuardrailError("GitHub CLI returned an unexpected JSON payload")
    return payload


def git_context(repo_root: Path) -> tuple[Path, Path, str]:
    worktree_root = Path(_git(repo_root, "rev-parse", "--show-toplevel")).resolve()
    common_dir = Path(
        _git(repo_root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    ).resolve()
    primary_root = common_dir.parent
    branch = _git(repo_root, "branch", "--show-current")
    if not branch:
        raise GuardrailError("writable tasks cannot run from a detached HEAD")
    return primary_root, worktree_root, branch


def validate_primary_main(primary_root: Path) -> None:
    root_branch = _git(primary_root, "branch", "--show-current")
    if root_branch != "main":
        raise GuardrailError(
            f"repository root worktree must stay on main; current branch is {root_branch}"
        )
    if _git(primary_root, "status", "--porcelain"):
        raise GuardrailError("repository root main worktree must stay clean")
    main_sha = _git(primary_root, "rev-parse", "main")
    origin_main_sha = _git(primary_root, "rev-parse", "origin/main")
    if main_sha != origin_main_sha:
        raise GuardrailError(
            f"repository root main must match origin/main; got "
            f"{main_sha} != {origin_main_sha}"
        )


def validate_worktree(repo_root: Path, task_id: str) -> dict[str, str]:
    normalized_task = normalize_task_id(task_id)
    primary_root, worktree_root, branch = git_context(repo_root)
    validate_primary_main(primary_root)
    expected_branch = f"agent/{normalized_task}"
    expected_worktree = (primary_root / ".worktrees" / normalized_task).resolve()
    if branch != expected_branch:
        raise GuardrailError(
            f"writable task must use branch {expected_branch}; current branch is {branch}"
        )
    if os.path.normcase(str(worktree_root)) != os.path.normcase(str(expected_worktree)):
        raise GuardrailError(
            f"writable task must use worktree {expected_worktree}; current worktree is "
            f"{worktree_root}"
        )
    return {
        "task_id": normalized_task,
        "branch": expected_branch,
        "worktree": f".worktrees/{normalized_task}",
    }


def _previous_event(
    events: list[dict[str, Any]], task_id: str
) -> dict[str, Any] | None:
    return latest_events_by_task(events).get(task_id)


def _validate_transition(previous_status: str | None, status: str) -> None:
    if status not in ALLOWED_STATUSES:
        raise GuardrailError(f"unsupported status: {status or '<empty>'}")
    allowed = ALLOWED_TRANSITIONS.get(previous_status, set())
    if status not in allowed:
        if previous_status is None:
            raise GuardrailError(f"task must start with STARTED, not {status}")
        raise GuardrailError(f"invalid task transition: {previous_status} -> {status}")


def _same_owned_paths(left: list[str], right: list[str]) -> bool:
    return [path.casefold() for path in left] == [path.casefold() for path in right]


def _validate_completed_context(
    *,
    repo_root: Path,
    task_id: str,
    owned_paths: list[str],
    declared_commit: str,
) -> tuple[str, list[str]]:
    validate_worktree(repo_root, task_id)
    if _git(repo_root, "status", "--porcelain"):
        raise GuardrailError(
            "COMPLETED requires a clean task worktree with every change committed"
        )
    if not _git_succeeds(repo_root, "merge-base", "--is-ancestor", "origin/main", "HEAD"):
        raise GuardrailError(
            "COMPLETED requires the task branch to contain the current origin/main"
        )
    commits_ahead = int(_git(repo_root, "rev-list", "--count", "origin/main..HEAD"))
    if commits_ahead < 1:
        raise GuardrailError("COMPLETED requires at least one task commit")

    head_commit = _git(repo_root, "rev-parse", "HEAD")
    if not declared_commit.strip():
        raise GuardrailError("COMPLETED requires the exact task commit")
    try:
        resolved_commit = _git(repo_root, "rev-parse", f"{declared_commit.strip()}^{{commit}}")
    except GuardrailError as exc:
        raise GuardrailError("COMPLETED commit does not resolve to a commit") from exc
    if resolved_commit != head_commit:
        raise GuardrailError(
            f"COMPLETED commit must equal task HEAD; got {resolved_commit} != {head_commit}"
        )

    changed_files = normalize_owned_paths(
        _git(repo_root, "diff", "--name-only", "--diff-filter=ACDMRTUXB", "origin/main...HEAD")
        .splitlines()
    )
    if not changed_files:
        raise GuardrailError("COMPLETED requires a nonempty committed diff")
    unauthorized = [
        path
        for path in changed_files
        if not any(path_is_owned(path, owned_path) for owned_path in owned_paths)
    ]
    if unauthorized:
        raise GuardrailError(
            "committed changes fall outside owned_paths: " + ", ".join(unauthorized)
        )
    return head_commit, changed_files


def _successful_check_names(checks: list[dict[str, Any]]) -> set[str]:
    successful: set[str] = set()
    for check in checks:
        name = str(check.get("name") or check.get("context") or "").strip()
        conclusion = str(check.get("conclusion") or check.get("state") or "").upper()
        if name and conclusion == "SUCCESS":
            successful.add(name)
    return successful


def _validate_merged_context(
    *,
    repo_root: Path,
    task_id: str,
    pr_number: int,
    approved_by: str,
    completed_commit: str,
) -> tuple[str, str]:
    primary_root, worktree_root, branch = git_context(repo_root)
    if os.path.normcase(str(worktree_root)) != os.path.normcase(str(primary_root)):
        raise GuardrailError("MERGED must be recorded from the repository root worktree")
    if branch != "main":
        raise GuardrailError(f"MERGED requires root branch main; current branch is {branch}")
    validate_primary_main(primary_root)
    if pr_number < 1:
        raise GuardrailError("MERGED requires a positive GitHub pull request number")
    if approved_by != MERGE_APPROVER:
        raise GuardrailError(f"MERGED requires ApprovedBy {MERGE_APPROVER}")

    raw_pr = _gh_json(
        primary_root,
        "pr",
        "view",
        str(pr_number),
        "--json",
        (
            "number,state,baseRefName,headRefName,headRefOid,mergeCommit,mergedBy,"
            "reviewDecision,reviews,statusCheckRollup"
        ),
    )
    if not isinstance(raw_pr, dict):
        raise GuardrailError("GitHub pull request query returned an unexpected payload")
    if str(raw_pr.get("state") or "").upper() != "MERGED":
        raise GuardrailError(f"GitHub PR #{pr_number} is not merged")
    if raw_pr.get("baseRefName") != "main":
        raise GuardrailError(f"GitHub PR #{pr_number} does not target main")
    expected_head = f"agent/{task_id}"
    if raw_pr.get("headRefName") != expected_head:
        raise GuardrailError(
            f"GitHub PR #{pr_number} head must be {expected_head}"
        )
    if str(raw_pr.get("headRefOid") or "") != completed_commit:
        raise GuardrailError(
            f"GitHub PR #{pr_number} head does not match the recorded COMPLETED commit"
        )

    merged_by = str((raw_pr.get("mergedBy") or {}).get("login") or "")
    approver_login = MERGE_APPROVER.removeprefix("@")
    if merged_by.casefold() != approver_login.casefold():
        raise GuardrailError(
            f"GitHub PR #{pr_number} must be merged by {MERGE_APPROVER}"
        )
    if str(raw_pr.get("reviewDecision") or "").upper() != "APPROVED":
        raise GuardrailError(f"GitHub PR #{pr_number} review decision is not APPROVED")
    reviews = [
        review
        for review in raw_pr.get("reviews") or []
        if isinstance(review, dict)
        and str((review.get("author") or {}).get("login") or "").casefold()
        == approver_login.casefold()
    ]
    reviews.sort(key=lambda review: str(review.get("submittedAt") or ""))
    if not reviews or str(reviews[-1].get("state") or "").upper() != "APPROVED":
        raise GuardrailError(
            f"GitHub PR #{pr_number} lacks a current approval from {MERGE_APPROVER}"
        )

    checks = [
        check
        for check in raw_pr.get("statusCheckRollup") or []
        if isinstance(check, dict)
    ]
    missing_checks = sorted(set(REQUIRED_CHECKS) - _successful_check_names(checks))
    if missing_checks:
        raise GuardrailError(
            f"GitHub PR #{pr_number} lacks successful required checks: "
            + ", ".join(missing_checks)
        )

    merge_commit = str((raw_pr.get("mergeCommit") or {}).get("oid") or "")
    if not merge_commit:
        raise GuardrailError(f"GitHub PR #{pr_number} has no merge commit")
    if not _git_succeeds(primary_root, "merge-base", "--is-ancestor", merge_commit, "main"):
        raise GuardrailError(
            f"local main does not contain GitHub PR #{pr_number} merge commit {merge_commit}"
        )
    return f"@{merged_by}", merge_commit


def validate_event(
    *,
    repo_root: Path,
    progress_path: Path,
    candidate: dict[str, Any],
) -> dict[str, Any]:
    status = str(candidate.get("status") or "").upper()
    task_id = normalize_task_id(str(candidate.get("task_id") or ""))
    events = read_events(progress_path)
    previous = _previous_event(events, task_id)
    previous_status = (
        str(previous.get("status") or "").upper() if previous is not None else None
    )
    _validate_transition(previous_status, status)

    owned_input = [str(value) for value in candidate.get("owned_paths") or []]
    read_only_value = candidate.get("read_only")
    branch = str(candidate.get("branch") or "")
    worktree = str(candidate.get("worktree") or "")
    if previous is None:
        owned_paths = normalize_owned_paths(owned_input)
        read_only = bool(read_only_value)
    else:
        previous_owned_paths = normalize_owned_paths(
            [str(value) for value in previous.get("owned_paths") or []]
        )
        candidate_owned_paths = normalize_owned_paths(owned_input)
        if candidate_owned_paths and not _same_owned_paths(
            candidate_owned_paths, previous_owned_paths
        ):
            raise GuardrailError("owned_paths cannot change after STARTED")
        owned_paths = previous_owned_paths

        previous_read_only = bool(previous.get("read_only"))
        if read_only_value is not None and bool(read_only_value) != previous_read_only:
            raise GuardrailError("read_only cannot change after STARTED")
        read_only = previous_read_only

        previous_branch = str(previous.get("branch") or "")
        previous_worktree = str(previous.get("worktree") or "")
        if branch and branch != previous_branch:
            raise GuardrailError("branch cannot change after STARTED")
        if (
            worktree
            and worktree.replace("\\", "/").rstrip("/")
            != previous_worktree.replace("\\", "/").rstrip("/")
        ):
            raise GuardrailError("worktree cannot change after STARTED")
        branch = previous_branch
        worktree = previous_worktree

    if status == "STARTED" and not read_only:
        expected = validate_worktree(repo_root, task_id)
        if branch and branch != expected["branch"]:
            raise GuardrailError(
                f"declared branch {branch} does not match {expected['branch']}"
            )
        if worktree and worktree.replace("\\", "/").rstrip("/") != expected["worktree"]:
            raise GuardrailError(
                f"declared worktree {worktree} does not match {expected['worktree']}"
            )
        branch = expected["branch"]
        worktree = expected["worktree"]
        if not owned_paths:
            raise GuardrailError("writable STARTED events require nonempty owned paths")
        conflicts = find_ownership_conflicts(
            task_id=task_id,
            owned_paths=owned_paths,
            events=events,
        )
        if conflicts:
            raise GuardrailError("; ".join(conflicts))
    elif not read_only and status != "MERGED":
        expected = validate_worktree(repo_root, task_id)
        if branch != expected["branch"] or worktree != expected["worktree"]:
            raise GuardrailError("task identity does not match its writable worktree")

    approved_by = str(candidate.get("approved_by") or "").strip()
    commit = str(candidate.get("commit") or "").strip()
    changed_files = normalize_owned_paths(
        [str(value) for value in candidate.get("changed_files") or []]
    )
    try:
        pr_number = int(candidate.get("pr_number") or 0)
    except (TypeError, ValueError) as exc:
        raise GuardrailError("pr_number must be an integer") from exc
    merge_commit = ""
    if status == "COMPLETED" and not read_only:
        commit, changed_files = _validate_completed_context(
            repo_root=repo_root,
            task_id=task_id,
            owned_paths=owned_paths,
            declared_commit=commit,
        )
    if status == "MERGED":
        if previous_status != "COMPLETED":
            raise GuardrailError("MERGED requires the previous task status to be COMPLETED")
        assert previous is not None
        completed_commit = str(previous.get("commit") or "").strip()
        if not completed_commit:
            raise GuardrailError("MERGED requires a commit-bound COMPLETED event")
        approved_by, merge_commit = _validate_merged_context(
            repo_root=repo_root,
            task_id=task_id,
            pr_number=pr_number,
            approved_by=approved_by,
            completed_commit=completed_commit,
        )
        changed_files = normalize_owned_paths(
            [str(value) for value in previous.get("changed_files") or []]
        )
        commit = merge_commit

    return {
        **candidate,
        "task_id": task_id,
        "status": status,
        "branch": branch,
        "worktree": worktree,
        "owned_paths": owned_paths,
        "read_only": read_only,
        "approved_by": approved_by,
        "changed_files": changed_files,
        "commit": commit,
        "pr_number": pr_number,
        "merge_commit": merge_commit,
    }


def check_policy(repo_root: Path) -> list[str]:
    required = (
        ".github/workflows/ci.yml",
        ".github/pull_request_template.md",
        ".github/CODEOWNERS",
        ".githooks/pre-push",
        "scripts/install_git_hooks.ps1",
        "scripts/task_worktree.ps1",
    )
    errors = [
        f"missing required workflow file: {path}"
        for path in required
        if not (repo_root / path).is_file()
    ]
    hook = repo_root / ".githooks" / "pre-push"
    if hook.is_file() and "refs/heads/main" not in hook.read_text(encoding="utf-8"):
        errors.append("pre-push hook does not guard refs/heads/main")
    return errors


def _parse_paths(value: str) -> list[str]:
    return [item for item in value.split(";") if item.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    normalize_parser = subparsers.add_parser("normalize-task-id")
    normalize_parser.add_argument("task_id")

    worktree_parser = subparsers.add_parser("validate-worktree")
    worktree_parser.add_argument("--repo-root", type=Path, required=True)
    worktree_parser.add_argument("--task-id", required=True)

    ownership_parser = subparsers.add_parser("check-ownership")
    ownership_parser.add_argument("--progress-path", type=Path, required=True)
    ownership_parser.add_argument("--task-id", required=True)
    ownership_parser.add_argument("--owned-paths", required=True)

    event_parser = subparsers.add_parser("validate-event")
    event_parser.add_argument("--repo-root", type=Path, required=True)
    event_parser.add_argument("--progress-path", type=Path, required=True)
    event_payload = event_parser.add_mutually_exclusive_group(required=True)
    event_payload.add_argument("--event-json")
    event_payload.add_argument("--event-base64")

    policy_parser = subparsers.add_parser("policy")
    policy_parser.add_argument("--repo-root", type=Path, default=Path.cwd())

    args = parser.parse_args(argv)
    try:
        if args.command == "normalize-task-id":
            print(normalize_task_id(args.task_id))
        elif args.command == "validate-worktree":
            print(
                json.dumps(
                    validate_worktree(args.repo_root.resolve(), args.task_id),
                    ensure_ascii=False,
                )
            )
        elif args.command == "check-ownership":
            task_id = normalize_task_id(args.task_id)
            owned_paths = normalize_owned_paths(_parse_paths(args.owned_paths))
            conflicts = find_ownership_conflicts(
                task_id=task_id,
                owned_paths=owned_paths,
                events=read_events(args.progress_path),
            )
            if conflicts:
                raise GuardrailError("; ".join(conflicts))
            print(json.dumps({"task_id": task_id, "owned_paths": owned_paths}))
        elif args.command == "validate-event":
            candidate = decode_event_payload(
                event_json=args.event_json,
                event_base64=args.event_base64,
            )
            print(
                json.dumps(
                    validate_event(
                        repo_root=args.repo_root.resolve(),
                        progress_path=args.progress_path.resolve(),
                        candidate=candidate,
                    ),
                    ensure_ascii=False,
                )
            )
        elif args.command == "policy":
            errors = check_policy(args.repo_root.resolve())
            if errors:
                raise GuardrailError("; ".join(errors))
            print("Repository policy guardrails OK")
    except (GuardrailError, json.JSONDecodeError) as exc:
        print(f"Repository guardrail rejected operation: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
