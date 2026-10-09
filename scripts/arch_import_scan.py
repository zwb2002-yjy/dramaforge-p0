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
    python scripts/arch_import_scan.py --check       # increment-only dependency gate
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
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

# Explicit permissions from MODULE_BOUNDARIES §two/four. Existing violations
# are individual debts, not a reason to widen these permissions.
ALLOWED = {
    "frontend": {"contract", "director", "creative", "production", "provider", "domain", "shared"},
    "contract": {"shared"},
    "director": {"creative", "domain", "contract", "shared"},
    "creative": {"domain", "shared"},
    "production": {"creative", "provider", "domain", "contract", "shared"},
    "provider": {"domain", "shared"},
    "domain": {"shared"},
    "shared": set(),
}
BASELINE = ROOT / "scripts" / "architecture-baseline.json"


def forbidden(source_module: str, target_module: str) -> bool:
    source, target = layer_of(source_module), layer_of(target_module)
    if source == target or "other" in (source, target):
        return False
    if source == "production" and target == "creative":
        return not (target_module == "app.director.creative_capabilities.contracts" or
                    target_module.startswith("app.director.creative_capabilities.contracts."))
    return target not in ALLOWED[source]


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


def imported_modules(
    tree: ast.AST, *, package: str, known_modules: set[str],
) -> set[str]:
    found: set[str] = set()
    import_helpers = {"__import__", "importlib.import_module"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
            for alias in node.names:
                if alias.name == "importlib":
                    import_helpers.add(f"{alias.asname or alias.name}.import_module")
        elif isinstance(node, ast.ImportFrom):
            target = importlib.util.resolve_name(
                "." * node.level + (node.module or ""), package,
            ) if node.level else (node.module or "")
            for alias in node.names:
                submodule = f"{target}.{alias.name}"
                found.add(submodule if submodule in known_modules else target)
                if target == "importlib" and alias.name == "import_module":
                    import_helpers.add(alias.asname or alias.name)
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and node.args
                and ast.unparse(node.func) in import_helpers
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            target = node.args[0].value
            explicit_package = next((keyword.value for keyword in node.keywords
                                     if keyword.arg == "package"), None)
            if explicit_package is None and len(node.args) > 1:
                explicit_package = node.args[1]
            resolved_package = (explicit_package.value if isinstance(explicit_package, ast.Constant)
                                and isinstance(explicit_package.value, str) else package)
            found.add(importlib.util.resolve_name(target, resolved_package)
                      if target.startswith(".") else target)
    return found


def build_edges() -> tuple[dict[tuple[str, str], set[str]], list[str]]:
    edges: dict[tuple[str, str], set[str]] = defaultdict(set)
    problems: list[str] = []
    if not APP.is_dir():
        raise SystemExit(f"backend package not found at {APP}")

    paths = [path for path in sorted(APP.rglob("*.py")) if "__pycache__" not in path.parts]
    known_modules = {module_name(path) for path in paths}
    for path in paths:
        module = module_name(path)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            package = module if path.name == "__init__.py" else module.rpartition(".")[0]
            targets = imported_modules(tree, package=package, known_modules=known_modules)
        except (SyntaxError, ImportError, ValueError) as exc:
            problems.append(f"PARSE-FAIL {module}: {exc}")
            continue
        source = layer_of(module)
        for target in targets:
            if not target.startswith("app."):
                continue
            destination = layer_of(target)
            if source != destination:
                edges[(source, destination)].add(f"{module} -> {target}")
    return edges, problems


def report_matrix(edges: dict[tuple[str, str], set[str]]) -> None:
    print("== layer dependency matrix (distinct module edges) ==")
    for (source, destination) in sorted(edges):
        marker = " FORBIDDEN" if any(forbidden(*edge.split(" -> "))
                                      for edge in edges[(source, destination)]) else ""
        print(
            f"{source:>10} -> {destination:<10} "
            f"{len(edges[(source, destination)]):3d}{marker}"
        )


def report_violations(edges: dict[tuple[str, str], set[str]]) -> int:
    print("== boundary crossings ==")
    total = 0
    for (source, destination), actual in sorted(edges.items()):
        members = {edge for edge in actual if forbidden(*edge.split(" -> "))}
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


def check_baseline(edges: dict[tuple[str, str], set[str]], path: Path) -> list[str]:
    actual = {edge for members in edges.values() for edge in members
              if forbidden(*edge.split(" -> "))}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("version") != 1 or not isinstance(payload.get("dependencies"), list):
            raise ValueError("expected version 1 and a dependencies list")
        baseline = set()
        for item in payload["dependencies"]:
            if not isinstance(item, dict) or any(
                not isinstance(item.get(key), str) or not item[key].strip()
                for key in ("from", "to", "reason")
            ):
                raise ValueError("every dependency needs from, to and a nonempty reason")
            edge = f"{item['from']} -> {item['to']}"
            if edge in baseline:
                raise ValueError(f"duplicate exemption: {edge}")
            baseline.add(edge)
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        return [f"INVALID-BASELINE {path}: {exc}"]
    return ([f"NEW-VIOLATION {edge}" for edge in sorted(actual - baseline)] +
            [f"STALE-EXEMPTION {edge}" for edge in sorted(baseline - actual)])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", action="store_true", help="layer matrix only")
    parser.add_argument(
        "--violations",
        action="store_true",
        help="boundary crossings only (informational; never fails the build)",
    )
    parser.add_argument("--check", action="store_true", help="fail on new violations or stale exemptions")
    parser.add_argument("--baseline", type=Path, default=BASELINE)
    args = parser.parse_args(argv)

    edges, problems = build_edges()
    for problem in problems:
        print(problem, file=sys.stderr)

    if args.check:
        problems.extend(check_baseline(edges, args.baseline))
        for problem in problems:
            print(problem, file=sys.stderr)
        if problems:
            return 1
        print("Architecture gate passed: no new dependency debt; baseline is current.")
        return 0
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
