#!/usr/bin/env python3
"""Report the backend module dependency graph for architecture reviews.

Read-only evidence tool. It parses ``backend/app/**.py`` with :mod:`ast` and
answers the two questions that architecture reviews keep re-deriving by hand:

1. Which layer imports which layer, and by how many distinct module edges?
2. Which concrete edges cross a boundary declared in
   ``docs/MODULE_BOUNDARIES.md``?

It does not import the application, touch a database, or need a running
service. Output is intended to be pasted into or reconciled against
``docs/ARCHITECTURE_MAPPING.md``.

Usage::

    python scripts/arch_import_scan.py               # full report
    python scripts/arch_import_scan.py --matrix      # layer matrix only
    python scripts/arch_import_scan.py --violations  # boundary crossings only
"""

from __future__ import annotations

import argparse
import ast
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "backend" / "app"

# Longest matching prefix wins. Keep in sync with docs/MODULE_BOUNDARIES.md §一.
LAYERS: tuple[tuple[str, str], ...] = (
    ("app.director.creative_capabilities", "creative"),
    ("app.production.application", "production"),
    ("app.director.runtime", "director"),
    ("app.director.workflows", "director"),
    ("app.director", "director"),
    ("app.production", "production"),
    ("app.execution", "production"),
    ("app.runtime", "production"),
    ("app.workbench", "production"),
    ("app.providers", "provider"),
    ("app.contracts", "contract"),
    ("app.access", "domain"),
    ("app.assets", "domain"),
    ("app.consistency", "domain"),
    ("app.delivery", "domain"),
    ("app.editing", "domain"),
    ("app.shared", "shared"),
    ("app.storage", "shared"),
    ("app.security", "shared"),
    ("app.events", "shared"),
    ("app.api", "frontend"),
    ("app.workers", "frontend"),
)

# Directed boundaries that docs/MODULE_BOUNDARIES.md §三 forbids.
FORBIDDEN: tuple[tuple[str, str], ...] = (
    ("creative", "director"),
    ("creative", "production"),
    ("creative", "provider"),
    ("creative", "frontend"),
    ("provider", "director"),
    ("provider", "production"),
    ("provider", "frontend"),
    ("contract", "director"),
    ("contract", "production"),
    ("contract", "provider"),
    ("domain", "director"),
    ("domain", "creative"),
    ("director", "provider"),
)


def layer_of(module: str) -> str:
    for prefix, name in LAYERS:
        if module == prefix or module.startswith(prefix + "."):
            return name
    return "other"


def module_name(path: Path) -> str:
    parts = list(path.relative_to(ROOT / "backend").with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def imported_modules(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            found.add(node.module)
    return found


def build_edges() -> tuple[dict[tuple[str, str], set[str]], list[str]]:
    edges: dict[tuple[str, str], set[str]] = defaultdict(set)
    problems: list[str] = []
    if not APP.is_dir():
        raise SystemExit(f"backend package not found at {APP}")

    for path in sorted(APP.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        module = module_name(path)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        except SyntaxError as exc:
            problems.append(f"PARSE-FAIL {module}: {exc}")
            continue
        source = layer_of(module)
        for target in imported_modules(tree):
            if not target.startswith("app."):
                continue
            destination = layer_of(target)
            if source != destination:
                edges[(source, destination)].add(f"{module} -> {target}")
    return edges, problems


def report_matrix(edges: dict[tuple[str, str], set[str]]) -> None:
    print("== layer dependency matrix (distinct module edges) ==")
    for (source, destination) in sorted(edges):
        marker = " FORBIDDEN" if (source, destination) in FORBIDDEN else ""
        print(
            f"{source:>10} -> {destination:<10} "
            f"{len(edges[(source, destination)]):3d}{marker}"
        )


def report_violations(edges: dict[tuple[str, str], set[str]]) -> int:
    print("== boundary crossings ==")
    total = 0
    for source, destination in sorted(FORBIDDEN):
        members = edges.get((source, destination))
        if not members:
            continue
        total += len(members)
        print(f"--- {source} -> {destination} ({len(members)}) ---")
        for line in sorted(members):
            print("   ", line)
    if total == 0:
        print("(none)")
    return total


def report_details(edges: dict[tuple[str, str], set[str]]) -> None:
    print()
    print("== all cross-layer edges ==")
    for (source, destination) in sorted(edges):
        print(f"--- {source} -> {destination} ({len(edges[(source, destination)])}) ---")
        for line in sorted(edges[(source, destination)]):
            print("   ", line)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", action="store_true", help="layer matrix only")
    parser.add_argument(
        "--violations",
        action="store_true",
        help="boundary crossings only (informational; never fails the build)",
    )
    args = parser.parse_args(argv)

    edges, problems = build_edges()
    for problem in problems:
        print(problem, file=sys.stderr)

    if args.matrix:
        report_matrix(edges)
    elif args.violations:
        report_violations(edges)
    else:
        report_matrix(edges)
        print()
        report_violations(edges)
        report_details(edges)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
