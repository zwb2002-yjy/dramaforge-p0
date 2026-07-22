#!/usr/bin/env python3
"""Enforce 03_全局目录规范.md directory and sensitive-file rules for CI.

Local build caches that are gitignored may exist on disk. This checker:
1. Rejects unregistered *root* entries that are not local-only.
2. Rejects sensitive credential files if present under the tree (not gitignored name).
3. When --git-index is used (default), also fails if forbidden paths are tracked by git.
4. Supports --demo-* flags to prove reject paths for BOOT-0 evidence.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# Registered top-level entries under the repo root (03 §1).
ALLOWED_ROOT = {
    ".gitattributes",
    ".gitignore",
    ".env.example",
    "01_项目总需求.md",
    "02_全栈技术栈锁定表.md",
    "03_全局目录规范.md",
    "04_数据定义全集.md",
    "05_模块落地约束.md",
    "06_受控混合Agent运行时规范.md",
    "DramaForge架构决策与技术选型书.md",
    "DramaForge双模式产品与架构汇报方案.md",
    "AI短剧工作台完整实施规划.md",
    "README.md",
    "agent.md",
    "AGENT.md",
    "AGENT_EXECUTION_PROTOCOL.md",
    "docker-compose.yml",
    "docker-compose.gpu.yml",
    "frontend",
    "backend",
    "infra",
    "scripts",
    "fixtures",
    "docs",
    ".agent-control",
    ".github",
    ".githooks",
}

# Local-only root names (gitignored or tooling); not product code.
LOCAL_ONLY_ROOT = {
    ".git",
    ".agents",
    ".codex",
    ".idea",
    ".vscode",
    ".playwright-mcp",
    ".worktrees",
    ".ruff_cache",
    ".mypy_cache",
    ".pytest_cache",
    ".run",
    "data",
    "tmp",
    "logs",
    "dump.rdb",
    "production-ui-demo.png",
    "node_modules",
    "dist",
    "coverage",
    ".venv",
    "venv",
    ".env",  # local secrets only; never committed
}

FORBIDDEN_TRACKED_PARTS = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    "dist",
    "coverage",
    ".venv",
    "venv",
    "htmlcov",
    "playwright-report",
    "test-results",
}

FORBIDDEN_SUFFIXES = {
    ".pem",
    ".key",
    ".p12",
    ".pfx",
}

FORBIDDEN_FILE_NAMES = {
    ".env",
    "id_rsa",
    "credentials.json",
    "service-account.json",
}


def check_root_entries(root: Path) -> list[str]:
    errors: list[str] = []
    for child in sorted(root.iterdir()):
        name = child.name
        if name in LOCAL_ONLY_ROOT or name.startswith(".git"):
            continue
        if name not in ALLOWED_ROOT:
            errors.append(f"unregistered root entry: {name}")
    return errors


def check_sensitive_on_disk(root: Path) -> list[str]:
    """Fail if credential-like files exist under the tree (excluding venv/node_modules)."""
    errors: list[str] = []
    skip_parts = FORBIDDEN_TRACKED_PARTS | {".git"}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(root).parts
        if any(part in skip_parts for part in rel_parts):
            continue
        name = path.name
        # Local gitignored root .env is expected for dev; git index check still blocks commit.
        if name == ".env" and path.parent == root:
            continue
        if name in FORBIDDEN_FILE_NAMES or (
            name.startswith(".env.") and name != ".env.example"
        ):
            rel = path.relative_to(root).as_posix()
            errors.append(f"forbidden env/credential file on disk: {rel}")
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            errors.append(f"forbidden sensitive file on disk: {path.relative_to(root).as_posix()}")
    return errors


def check_git_index(root: Path) -> list[str]:
    """Fail if git tracks build caches or secrets."""
    errors: list[str] = []
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "ls-files"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return ["git executable not found for index check"]
    if proc.returncode != 0:
        # Empty repo with no commits still allows ls-files of staged/untracked? ls-files returns 0.
        if "not a git repository" in (proc.stderr or "").lower():
            return []
        # Unborn branch: ls-files still works for tracked; if fails, skip.
        return []

    for line in proc.stdout.splitlines():
        path = line.strip().replace("\\", "/")
        if not path:
            continue
        parts = path.split("/")
        name = parts[-1]
        if any(part in FORBIDDEN_TRACKED_PARTS for part in parts):
            errors.append(f"forbidden path tracked by git: {path}")
        if name in FORBIDDEN_FILE_NAMES or (
            name.startswith(".env.") and name != ".env.example"
        ):
            errors.append(f"forbidden credential tracked by git: {path}")
        suffix = Path(name).suffix.lower()
        if suffix in FORBIDDEN_SUFFIXES:
            errors.append(f"forbidden sensitive suffix tracked by git: {path}")
    return errors


def check_demo_rejects(demo_unregistered: Path | None, demo_sensitive: Path | None) -> list[str]:
    errors: list[str] = []
    if demo_unregistered is not None:
        name = (
            demo_unregistered.name
            if demo_unregistered.suffix or demo_unregistered.parent != Path()
            else str(demo_unregistered)
        )
        # Accept bare names like "utils2"
        label = str(demo_unregistered)
        if label in ALLOWED_ROOT or label in LOCAL_ONLY_ROOT:
            errors.append(f"demo unregistered path is incorrectly allowed: {label}")
        else:
            print(f"REJECT unregistered: {label}")
    if demo_sensitive is not None:
        label = str(demo_sensitive)
        name = Path(label).name
        suffix = Path(label).suffix.lower()
        if (
            name in FORBIDDEN_FILE_NAMES
            or name in FORBIDDEN_TRACKED_PARTS
            or suffix in FORBIDDEN_SUFFIXES
            or (name.startswith(".env.") and name != ".env.example")
        ):
            print(f"REJECT sensitive/build: {label}")
        else:
            errors.append(f"demo sensitive path not classified as forbidden: {label}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root",
    )
    parser.add_argument(
        "--skip-git-index",
        action="store_true",
        help="Skip git ls-files check (disk root + sensitive only)",
    )
    parser.add_argument("--demo-unregistered", type=Path, default=None)
    parser.add_argument("--demo-sensitive", type=Path, default=None)
    args = parser.parse_args(argv)
    root = args.root.resolve()

    errors: list[str] = []
    errors.extend(check_root_entries(root))
    errors.extend(check_sensitive_on_disk(root))
    if not args.skip_git_index:
        errors.extend(check_git_index(root))
    errors.extend(check_demo_rejects(args.demo_unregistered, args.demo_sensitive))

    if errors:
        print("Directory compliance FAILED:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print("Directory compliance OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
