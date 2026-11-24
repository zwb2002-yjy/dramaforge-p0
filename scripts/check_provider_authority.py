#!/usr/bin/env python3
"""Check the legacy/new provider authority map against the tree.

`scripts/provider_authority_map.json` is the machine-checkable map from the
legacy provider surface (dict adapters, dead Protocol/DTOs, fake modules) to
the current authority (ModelAdapter / CapabilityRouter / Compiler / Runtime).
This script recomputes the caller counts instead of trusting the note:

- DELETE entries with ``retired: false`` must have no production caller
  outside ``defined_in``/``path`` and must name replacements that exist.
- DELETE entries with ``retired: true`` must be gone from ``backend/app``.
- KEEP entries must still exist in ``backend/app``.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = Path(__file__).with_name("provider_authority_map.json")
APP_DIR = ROOT / "backend" / "app"
SKIPPED_PARTS = {".venv", "__pycache__", "node_modules", ".git"}


def _python_files(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*.py")
        if path.is_file() and not SKIPPED_PARTS.intersection(path.parts)
    )


def _symbol_hits(symbol: str, files: list[Path]) -> dict[str, int]:
    pattern = re.compile(rf"\b{re.escape(symbol)}\b")
    hits: dict[str, int] = {}
    for path in files:
        count = len(pattern.findall(path.read_text(encoding="utf-8", errors="replace")))
        if count:
            hits[str(path.relative_to(ROOT)).replace("\\", "/")] = count
    return hits


def _module_importers(module: str, files: list[Path], own_path: str) -> list[str]:
    pattern = re.compile(
        rf"^\s*(?:from {re.escape(module)}(?:\.\w+)* import|import {re.escape(module)}(?:\s|$))"
    )
    importers: list[str] = []
    for path in files:
        relative = str(path.relative_to(ROOT)).replace("\\", "/")
        if relative == own_path:
            continue
        if any(pattern.match(line) for line in path.read_text(encoding="utf-8").splitlines()):
            importers.append(relative)
    return importers


def _replacement_missing(replacement: str, sources: dict[Path, str]) -> bool:
    if replacement.startswith("app."):
        path = APP_DIR / Path(*replacement.split(".")[1:])
        return not (path.with_suffix(".py").is_file() or path.is_dir())
    pattern = re.compile(rf"\b{re.escape(replacement)}\b")
    return not any(pattern.search(source) for source in sources.values())


def main() -> int:
    payload = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    entries = payload["entries"]
    files = _python_files(APP_DIR)
    sources = {path: path.read_text(encoding="utf-8", errors="replace") for path in files}
    failures: list[str] = []
    report: list[str] = []

    for entry in entries:
        decision = entry["decision"]
        if entry["kind"] == "symbol":
            symbol = entry["symbol"]
            defined_in = entry["defined_in"]
            hits = _symbol_hits(symbol, files)
            callers = {path: count for path, count in hits.items() if path != defined_in}
            exists = defined_in in hits
            if decision == "KEEP":
                if not exists:
                    failures.append(f"{symbol}: KEEP entry is missing from {defined_in}")
                report.append(f"KEEP   {symbol:26} callers={len(callers)} defined={exists}")
            else:
                if entry.get("retired"):
                    if hits:
                        failures.append(
                            f"{symbol}: retired but still present in {sorted(hits)}"
                        )
                    report.append(f"RETIRED {symbol:25} absent={not hits}")
                else:
                    if callers:
                        failures.append(
                            f"{symbol}: DELETE entry still has production callers {sorted(callers)}"
                        )
                    if not exists:
                        failures.append(
                            f"{symbol}: DELETE entry is already gone; flip retired=true"
                        )
                    report.append(
                        f"DELETE {symbol:26} callers={len(callers)} defined={exists}"
                    )
        else:
            module = entry["module"]
            own_path = entry["path"]
            existing = (ROOT / own_path).is_file()
            importers = _module_importers(module, files, own_path) if existing else []
            if decision == "KEEP":
                if not existing:
                    failures.append(f"{module}: KEEP entry is missing from {own_path}")
                report.append(f"KEEP   {module:26} importers={len(importers)}")
            else:
                if entry.get("retired"):
                    if existing:
                        failures.append(f"{module}: retired but {own_path} still exists")
                    report.append(f"RETIRED {module:25} absent={not existing}")
                else:
                    allowed = set(entry.get("allowed_current_importers", []))
                    unexpected = [path for path in importers if path not in allowed]
                    if unexpected:
                        failures.append(
                            f"{module}: DELETE entry still imported by {unexpected}"
                        )
                    for path in allowed:
                        owners = [
                            other
                            for other in entries
                            if other.get("path") == path and other["decision"] == "DELETE"
                        ]
                        if not owners:
                            failures.append(
                                f"{module}: allowed importer {path} is not a DELETE entry"
                            )
                    if not existing:
                        failures.append(
                            f"{module}: DELETE entry is already gone; flip retired=true"
                        )
                    report.append(
                        f"DELETE {module:26} importers={len(importers)} present={existing}"
                    )
        if decision == "DELETE":
            for replacement in entry.get("replacement", []):
                if _replacement_missing(replacement, sources):
                    owner = entry.get("symbol") or entry.get("module")
                    failures.append(f"{owner}: replacement {replacement} not found")

    for line in report:
        print(line)
    if failures:
        print("\nProvider authority check FAILED:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print("Provider authority check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
