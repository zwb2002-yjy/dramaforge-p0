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
    "LEGACY_" + "COMPAT",
    "litellm/text-" + "llm",
    "shot_" + "experiment_id",
    "translate_" + "v2",
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
    "start_" + "shot_nodes",
    "upload_" + "manual_media",
    "allow_" + "trial_without_quality_gate",
    "professional_" + "trial_bootstrap_allowed",
    "trial_" + "quality_gate_exception",
    "audited_" + "manual_upload",
    "manual_" + "media",
    "/projects/" + "{project_id}/generations",
    "/generations/" + "{operation_id}/cancel",
    "provider-" + "credentials",
    "settings_for_workspace_" + "provider",
    "Experiment" + "Service",
    "ExperimentCreate" + "Input",
    "ExecuteKeyframe" + "Result",
    "/projects/" + "{project_id}/dispatch",
    "/projects/" + "{project_id}/node-runs/{node_run_id}/enqueue",
)
FORBIDDEN_FILES = (
    ROOT / "backend" / "app" / "production" / "archive_models.py",
    ROOT / "backend" / "app" / "providers" / "generation_service.py",
    ROOT / "backend" / "app" / "providers" / "model_system_models.py",
    ROOT / "backend" / "app" / "providers" / "binding_cutover.py",
    ROOT / "backend" / "app" / "production" / "cutover_identity.py",
    ROOT / "backend" / "app" / "production" / "policy_models.py",
    ROOT / "backend" / "app" / "providers" / "catalog_seed_data.py",
    ROOT / "backend" / "app" / "providers" / "workspace_router.py",
    ROOT / "backend" / "app" / "creation",
    ROOT / "backend" / "app" / "shared" / "ids.py",
    ROOT / "backend" / "app" / "providers" / "connection.py",
    ROOT / "backend" / "app" / "api" / "v1" / "characters.py",
    ROOT / "backend" / "app" / "api" / "v1" / "credentials.py",
    ROOT
    / "frontend"
    / "src"
    / "components"
    / "provider"
    / "WorkspaceTextCredentialSettings.tsx",
    ROOT / "backend" / "app" / "api" / "v1" / "shot_ops.py",
    ROOT / "backend" / "app" / "director" / "legacy_guard.py",
    ROOT / "backend" / "app" / "director" / "execution_guard.py",
    ROOT / "backend" / "app" / "director" / "registry.py",
    ROOT / "backend" / "app" / "director" / "enums.py",
    ROOT / "backend" / "app" / "providers" / "flux.py",
    ROOT / "backend" / "app" / "providers" / "kling.py",
    ROOT / "backend" / "app" / "execution" / "shot_review.py",
    ROOT / "backend" / "app" / "delivery" / "export_service.py",
    ROOT / "backend" / "app" / "delivery" / "export_local.py",
    ROOT / "scripts" / "rerun_drift_blocks.py",
    ROOT / "frontend" / "src" / "routes" / "projects.$projectId.quick.tsx",
)
FORBIDDEN_PATH_TEXT = {
    ROOT / "backend" / "app" / "api" / "v1" / "experiments.py": (
        "accepted_" + "without_candidate",
    ),
    ROOT / "backend" / "app" / "editing" / "proposal_plan.py": (
        '"session_' + 'id"',
        '"timeline_' + 'plan"',
        'aliases = ("kind", "type", "op")',
    ),
    ROOT / "backend" / "app" / "production" / "repair_service.py": (
        "def execute_" + "repair(",
        "def create_and_" + "execute_first_step(",
    ),
    ROOT / "backend" / "app" / "director" / "business_checkpoints.py": (
        "def track_" + "execution(",
    ),
}

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
                failures.append(
                    f"{path.relative_to(ROOT)} contains retired token {token!r}"
                )
    for path, tokens in FORBIDDEN_PATH_TEXT.items():
        if not path.is_file():
            continue
        source = path.read_text(encoding="utf-8", errors="replace")
        for token in tokens:
            if token in source:
                failures.append(
                    f"{path.relative_to(ROOT)} contains retired compatibility token {token!r}"
                )
    if failures:
        print("Canonical surface check FAILED:", file=sys.stderr)
        print(
            "\n".join(f"  - {failure}" for failure in sorted(set(failures))),
            file=sys.stderr,
        )
        return 1
    print("Canonical surface check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
