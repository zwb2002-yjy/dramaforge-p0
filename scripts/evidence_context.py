#!/usr/bin/env python3
"""Commit-bound context for generated acceptance evidence."""

from __future__ import annotations

import os
import platform
import re
import subprocess
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SENSITIVE_OPTION_RE = re.compile(
    r"(?i)(api[_-]?key|authorization|credential|password|secret|token)"
)
INLINE_SECRET_RE = re.compile(
    r"(?i)\b(api[_-]?key|authorization|credential|password|secret|token)=([^\s]+)"
)


class EvidenceSourceError(RuntimeError):
    """Raised when evidence cannot be tied to one clean source commit."""


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


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
        message = (proc.stderr or proc.stdout).strip() or "git command failed"
        raise EvidenceSourceError(message)
    return proc.stdout.strip()


def capture_source(repo_root: Path) -> dict[str, Any]:
    root = repo_root.resolve()
    commit = _git(root, "rev-parse", "HEAD")
    status = _git(root, "status", "--porcelain=v1", "--untracked-files=normal")
    return {
        "source_commit": commit,
        "dirty": bool(status),
        "captured_at_utc": utc_now(),
    }


def sanitize_command(argv: Sequence[str]) -> list[str]:
    sanitized: list[str] = []
    redact_next = False
    for raw_arg in argv:
        arg = str(raw_arg)
        if redact_next:
            sanitized.append("[REDACTED]")
            redact_next = False
            continue
        if arg.startswith("-") and "=" in arg:
            option, value = arg.split("=", 1)
            rendered = (
                f"{option}=[REDACTED]"
                if SENSITIVE_OPTION_RE.search(option)
                else f"{option}={value}"
            )
            sanitized.append(rendered)
            continue
        sanitized.append(INLINE_SECRET_RE.sub(r"\1=[REDACTED]", arg))
        if arg.startswith("-") and SENSITIVE_OPTION_RE.search(arg):
            redact_next = True
    return sanitized


def environment_summary(*, cwd: Path | None = None) -> dict[str, Any]:
    return {
        "python_version": platform.python_version(),
        "python_executable": Path(sys.executable).name,
        "platform": platform.platform(),
        "cwd": str((cwd or Path.cwd()).resolve()),
        "app_env": os.getenv("APP_ENV"),
        "ci": os.getenv("CI"),
        "wsl_distro_name": os.getenv("WSL_DISTRO_NAME"),
    }


def begin_evidence_context(
    repo_root: Path,
    *,
    argv: Sequence[str] | None = None,
) -> dict[str, Any]:
    source = capture_source(repo_root)
    return {
        **source,
        "started_at_utc": source["captured_at_utc"],
        "command_summary": sanitize_command(argv if argv is not None else sys.argv),
        "environment": environment_summary(),
    }


def finish_evidence_context(
    context: dict[str, Any],
    repo_root: Path,
) -> dict[str, Any]:
    ending = capture_source(repo_root)
    source_commit = str(context.get("source_commit") or "")
    start_dirty = bool(context.get("dirty"))
    ending_commit = str(ending["source_commit"])
    ending_dirty = bool(ending["dirty"])
    consistent = (
        bool(source_commit)
        and not start_dirty
        and not ending_dirty
        and ending_commit == source_commit
    )
    return {
        **context,
        "ended_at_utc": ending["captured_at_utc"],
        "ending_source_commit": ending_commit,
        "ending_dirty": ending_dirty,
        "source_consistent": consistent,
    }


def default_evidence_dir(repo_root: Path, source_commit: str, kind: str) -> Path:
    safe_kind = kind.strip().lower()
    if safe_kind not in {"formal", "gate"}:
        raise ValueError(f"unsupported evidence kind: {kind}")
    return repo_root.resolve() / "tmp" / "p0-evidence" / source_commit / safe_kind


def require_ignored_evidence_path(repo_root: Path, path: Path) -> Path:
    root = repo_root.resolve()
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError:
        return resolved
    proc = subprocess.run(
        ["git", "-C", str(root), "check-ignore", "--quiet", "--", relative.as_posix()],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise EvidenceSourceError(
            f"evidence output inside the repository must be ignored by Git: {relative}"
        )
    return resolved


def evidence_source_errors(
    evidence: dict[str, Any],
    *,
    expected_commit: str,
) -> list[str]:
    errors: list[str] = []
    source_commit = str(evidence.get("source_commit") or "")
    ending_commit = str(evidence.get("ending_source_commit") or "")
    if source_commit != expected_commit:
        errors.append(
            f"source_commit={source_commit or '<missing>'} expected={expected_commit}"
        )
    if evidence.get("dirty") is not False:
        errors.append(f"dirty={evidence.get('dirty')!r}")
    if ending_commit != source_commit:
        errors.append(
            f"ending_source_commit={ending_commit or '<missing>'} "
            f"source_commit={source_commit or '<missing>'}"
        )
    if evidence.get("ending_dirty") is not False:
        errors.append(f"ending_dirty={evidence.get('ending_dirty')!r}")
    if evidence.get("source_consistent") is not True:
        errors.append(f"source_consistent={evidence.get('source_consistent')!r}")
    return errors
