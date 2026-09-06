#!/usr/bin/env python3
"""Fail if active documentation links the removed legacy planning set."""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
ACTIVE = (
    REPO / "AGENTS.md",
    REPO / "CLAUDE.md",
    REPO / "CONTRIBUTING.md",
    REPO / "README.md",
    REPO / "agent.md",
    REPO / "AGENT_EXECUTION_PROTOCOL.md",
    REPO / "docs" / "README.md",
)
RUNBOOKS = tuple((REPO / "docs" / "runbooks").glob("*.md"))
LEGACY_LINK = re.compile(r"\]\([^)]*(?:docs/current/|current/[0-9])")
LEGACY_AUTHORITY = re.compile(r"(?:docs/current/|当前执行合同).*(?:为准|唯一|权威)")

errors: list[str] = []
for path in (*ACTIVE, *RUNBOOKS):
    text = path.read_text(encoding="utf-8")
    if LEGACY_LINK.search(text):
        errors.append(f"legacy planning link: {path.relative_to(REPO)}")
    if LEGACY_AUTHORITY.search(text):
        errors.append(f"legacy planning authority claim: {path.relative_to(REPO)}")

if errors:
    raise SystemExit("\n".join(errors))
print("active planning references use the seven-plan program")
