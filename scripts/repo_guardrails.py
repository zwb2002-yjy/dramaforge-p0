#!/usr/bin/env python3
"""Check current workflow entrypoints, not a parallel task/approval ledger."""

from __future__ import annotations

import argparse
from pathlib import Path


def check_policy(repo_root: Path) -> list[str]:
    required = (
        ".github/workflows/ci.yml",
        ".github/pull_request_template.md",
        ".github/CODEOWNERS",
        ".githooks/pre-push",
        "scripts/install_git_hooks.ps1",
    )
    return [
        f"missing required workflow file: {path}"
        for path in required
        if not (repo_root / path).is_file()
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    policy = commands.add_parser("policy")
    policy.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    errors = check_policy(args.repo_root.resolve())
    if errors:
        print("\n".join(errors))
        return 2
    print("Repository workflow entrypoints OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
