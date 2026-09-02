#!/usr/bin/env python3
"""Fail when a retired product surface is reintroduced."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = (
    ROOT / "backend" / "app",
    ROOT / "frontend" / "src",
    ROOT / "scripts",
    ROOT / "fixtures",
)

# Keep the spellings split so this checker cannot report its own policy table.
FORBIDDEN_TEXT = (
    "/projects/" + "$projectId/quick",
    "p0_" + "10_shots",
    "exactly " + "10",
    "/creation/" + "start-project",
    "creation-" + "state",
    "produce-" + "golden",
    "confirm_" + "plan_and_materialize",
    "characters/" + "lead",
    "production_" + "batch_id",
    "budget_" + "reservation_id",
    "app." + "creation",
    "Director" + "WorkflowRun",
    "Character" + "Reference",
    "experience_" + "mode",
    "PROVIDER_" + "UNIFIED_PATH_ENABLED",
    "TEXT_" + "V3_ROUTER_ENABLED",
)
FORBIDDEN_FILES = (
    ROOT / "backend" / "app" / "creation",
    ROOT / "backend" / "app" / "api" / "v1" / "characters.py",
    ROOT / "backend" / "app" / "api" / "v1" / "shot_ops.py",
    ROOT / "backend" / "app" / "director" / "legacy_guard.py",
    ROOT / "backend" / "app" / "director" / "execution_guard.py",
    ROOT / "frontend" / "src" / "routes" / "projects.$projectId.quick.tsx",
)
IGNORED_PARTS = {".git", ".venv", "node_modules", "__pycache__", "dist", "tmp"}


def _files() -> list[Path]:
    return [
        path
        for root in SCAN_ROOTS
        for path in root.rglob("*")
        if path.is_file() and not IGNORED_PARTS.intersection(path.parts)
    ]


def main() -> int:
    failures: list[str] = []
    for path in FORBIDDEN_FILES:
        source_exists = (
            path.is_file()
            or path.is_dir()
            and any(
                child.is_file()
                and child.suffix == ".py"
                and not IGNORED_PARTS.intersection(child.parts)
                for child in path.rglob("*.py")
            )
        )
        if source_exists:
            failures.append(f"retired file/directory exists: {path.relative_to(ROOT)}")
    for path in _files():
        if path.resolve() == Path(__file__).resolve():
            continue
        source = path.read_text(encoding="utf-8", errors="replace")
        for token in FORBIDDEN_TEXT:
            if token in source:
                failures.append(f"{path.relative_to(ROOT)} contains retired token {token!r}")
    if failures:
        print("Canonical surface check FAILED:", file=sys.stderr)
        print("\n".join(f"  - {failure}" for failure in sorted(set(failures))), file=sys.stderr)
        return 1
    print("Canonical surface check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
