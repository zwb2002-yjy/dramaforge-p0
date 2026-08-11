"""V3 Architecture Boundary Test (spec §68, Phase 12).

Business code must depend on :class:`Capability` + :class:`CapabilityRouter` +
typed contracts — never on a concrete provider module. This test scans every
business source file under ``backend/app`` (excluding ``providers/``) for
imports of concrete provider modules and fails on any file outside an explicit
LEGACY_COMPAT allowlist. The allowlist pins the legacy surface so it can only
shrink (Phase 12 removes the exceptions), never grow.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
APP_DIR = REPO_ROOT / "backend" / "app"

# Concrete provider modules business code must not import. The abstraction
# modules (capabilities, router, contracts, manifest, registry, adapters_v2,
# workspace_router, ...) are allowed.
_FORBIDDEN_PROVIDER_MODULES = (
    "app.providers.agnes",
    "app.providers.volcengine",
    "app.providers.flux",
    "app.providers.kling",
    "app.providers.openai",
    "app.providers.local_tts",
    "app.providers.comfyui",
    "app.providers.azure_tts",
    "app.providers.fake",
)

# LEGACY_COMPAT: business files still reaching into concrete provider modules.
# Each entry is (path, removal condition). These are the pre-V3 paths that are
# being retired; the boundary test refuses any new file from doing the same.
LEGACY_COMPAT: dict[str, str] = {
    "creation/service.py": (
        "text LLM via openai getter (Agent brief/plan); remove when the V3 text "
        "model bridge is wired (P1)"
    ),
    "execution/product_path.py": (
        "legacy adapter branch gated by PROVIDER_UNIFIED_PATH_ENABLED (B6) + "
        "test Fake import; remove when the legacy branch is deleted"
    ),
    "execution/golden_path.py": "legacy P0 scaffolding using the Fake adapter",
    "execution/pipeline.py": "legacy P0 scaffolding using the Fake adapter",
    "execution/shot_p0.py": "legacy P0 scaffolding using the Fake adapter",
}

_IMPORT_RE = re.compile(
    r"^\s*(?:from (app\.providers\.[a-z_0-9]+) import|import (app\.providers\.[a-z_0-9]+))\b"
)


def _business_files() -> list[Path]:
    return sorted(
        path
        for path in APP_DIR.rglob("*.py")
        if path.is_file() and "providers" not in path.relative_to(APP_DIR).parts
    )


def _rel(path: Path) -> str:
    return str(path.relative_to(APP_DIR)).replace("\\", "/")


def _concrete_imports(path: Path) -> list[str]:
    hits: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _IMPORT_RE.match(line)
        if not match:
            continue
        module = match.group(1) or match.group(2)
        if module in _FORBIDDEN_PROVIDER_MODULES:
            hits.append(module)
    return hits


def test_architecture_boundary_business_never_imports_concrete_providers() -> None:
    violations: dict[str, list[str]] = {}
    for path in _business_files():
        rel = _rel(path)
        imports = _concrete_imports(path)
        if not imports:
            continue
        if rel in LEGACY_COMPAT:
            continue
        violations[rel] = imports
    assert not violations, (
        "business code imports concrete provider modules: "
        + "; ".join(f"{path} -> {mods}" for path, mods in sorted(violations.items()))
    )


def test_legacy_compat_surface_is_exactly_pinned() -> None:
    """No new business file may import a concrete provider; the LEGACY_COMPAT
    set is the complete, documented legacy surface."""
    importers = {
        _rel(path)
        for path in _business_files()
        if _concrete_imports(path)
    }
    assert set(LEGACY_COMPAT) >= importers, (
        f"legacy surface grew: {sorted(importers - set(LEGACY_COMPAT))}"
    )


def test_legacy_compat_entries_exist() -> None:
    for rel in LEGACY_COMPAT:
        assert (APP_DIR / rel).is_file(), f"LEGACY_COMPAT path missing: {rel}"


def test_providers_layer_never_imports_api_routes() -> None:
    """The dependency direction is one-way: providers must never import the
    HTTP/API layer. (Providers legitimately read shared data models from
    access/execution/creation for lineage and RLS; the hard boundary is that
    provider logic never knows about API routes.)"""
    forbidden_parents = ("app.api",)
    for path in (APP_DIR / "providers").rglob("*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            for parent in forbidden_parents:
                assert parent not in line, f"providers/{path.name} imports {parent}: {line}"


# Spec §126: business code must never *branch* on a concrete provider name.
# The provider-management surface (credentials / provider-connections / config
# settings) legitimately names providers; legacy product_path is already pinned
# as LEGACY_COMPAT. Everything else must route through Capability + ModelSlot.
_PROVIDER_BRANCH_RE = re.compile(
    r"(if |elif |\band\b|\bor\b|\bnot\b|\bin\b).*"
    r"(minimax|volcengine|agnes|kling|jimeng|seedance|seedream)"
)
_PROVIDER_BRANCH_ALLOWLIST = {
    "config.py",
    "execution/product_path.py",  # LEGACY_COMPAT (B6)
}


def test_business_code_never_branches_on_provider_names() -> None:
    violations: dict[str, list[str]] = {}
    for path in _business_files():
        rel = _rel(path)
        if rel in _PROVIDER_BRANCH_ALLOWLIST:
            continue
        hits = [
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if _PROVIDER_BRANCH_RE.search(line)
        ]
        if hits:
            violations[rel] = hits
    assert not violations, (
        "business code branches on provider names: "
        + "; ".join(f"{path}: {lines[0]}" for path, lines in sorted(violations.items()))
    )
