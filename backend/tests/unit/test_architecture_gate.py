"""Incremental dependency policy: no new debt, stale exemptions, or import loopholes."""

import ast
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "architecture_scan", ROOT / "scripts/arch_import_scan.py"
)
scan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scan)


@pytest.mark.parametrize(
    "statement",
    [
        "import app.providers.runtime",
        "from app.providers.runtime import Adapter",
        "from ..providers import runtime",
        "from app import providers",
        "from importlib import import_module as load; load('app.providers.runtime')",
        "from importlib import import_module as load; load('.runtime', package='app.providers')",
    ],
)
def test_import_spellings_cannot_hide_provider_dependency(statement):
    modules = scan.imported_modules(
        ast.parse(statement),
        package="app.director",
        known_modules={"app.providers", "app.providers.runtime"},
    )
    assert any(scan.forbidden("app.director.test", target) for target in modules)


@pytest.mark.parametrize(
    "source,target,blocked",
    [
        ("app.contracts.command", "app.production.reference_intents", True),
        ("app.contracts.command", "app.shared.errors", False),
        ("app.production.worker", "app.director.turn_service", True),
        ("app.production.worker", "app.director.creative_capabilities.contracts", False),
        ("app.production.worker", "app.director.creative_capabilities.contracts_extra", True),
        ("app.providers.runtime", "app.production.service", True),
        ("app.shared.helper", "app.access.models", True),
        ("app.access.service", "app.production.service", True),
        ("app.api.v1.test", "app.production.service", False),
    ],
)
def test_documented_permissions_are_not_widened_for_current_code(source, target, blocked):
    assert scan.forbidden(source, target) is blocked


def test_inbound_roles_are_distinct_without_reclassifying_application_debt():
    assert scan.layer_of("app.api.v1.workbench") == "backend_api"
    assert scan.layer_of("app.workers.jobs") == "backend_worker"
    assert scan.layer_of("app.production.application.commands") == "production"
    # An application responsibility in a mixed domain package is still debt;
    # calling it Application must not silently grant new import permissions.
    assert scan.layer_of("app.access.projects") == "domain"
    assert scan.forbidden("app.access.projects", "app.director.creative_capabilities.freeze")


@pytest.mark.parametrize("entry", ["app.api.v1.workbench", "app.workers.jobs"])
@pytest.mark.parametrize("target", [
    "app.contracts.command", "app.director.turn_service", "app.production.service",
    "app.providers.runtime", "app.assets.models", "app.shared.errors",
    "app.api.v1.workbench", "app.workers.jobs",
])
def test_inbound_split_preserves_import_matrix_and_reverse_boundaries(entry, target):
    assert not scan.forbidden(entry, target)
    if not target.startswith(("app.api.", "app.workers.")):
        assert scan.forbidden(target, entry)


def baseline(path, dependencies):
    path.write_text(json.dumps({"version": 1, "dependencies": dependencies}))
    return path


def test_gate_rejects_new_debt_and_stale_exemptions(tmp_path):
    edge = "app.director.old -> app.providers.runtime"
    edges = {("director", "provider"): {edge}}
    path = baseline(tmp_path / "baseline.json", [])
    assert scan.check_baseline(edges, path) == ["NEW-VIOLATION " + edge]
    item = {"from": "app.director.old", "to": "app.providers.runtime", "reason": "Existing debt"}
    baseline(path, [item])
    assert scan.check_baseline(edges, path) == []
    assert scan.check_baseline({}, path) == ["STALE-EXEMPTION " + edge]
    baseline(path, [item, item])
    assert "INVALID-BASELINE" in scan.check_baseline(edges, path)[0]
    baseline(path, [{**item, "reason": ""}])
    assert "INVALID-BASELINE" in scan.check_baseline(edges, path)[0]


def test_check_fails_closed_when_a_source_cannot_be_parsed(tmp_path, monkeypatch):
    app = tmp_path / "backend/app"
    app.mkdir(parents=True)
    (app / "broken.py").write_text("def broken(:")
    monkeypatch.setattr(scan, "ROOT", tmp_path)
    monkeypatch.setattr(scan, "APP", app)
    path = baseline(tmp_path / "baseline.json", [])
    assert scan.main(["--check", "--baseline", str(path)]) == 1


def test_baseline_is_a_no_new_debt_gate_not_an_all_compliant_claim():
    edges, problems = scan.build_edges()
    assert not problems
    assert scan.check_baseline(edges, scan.BASELINE) == []
    assert json.loads(scan.BASELINE.read_text())["dependencies"]


def test_reference_contract_is_the_same_class_for_existing_compiler_consumers():
    from app.contracts.shot_reference import ShotReferenceIntent
    from app.production.reference_intents import ShotReferenceIntent as CompilerIntent

    assert CompilerIntent is ShotReferenceIntent
    assert ShotReferenceIntent.__module__ == "app.contracts.shot_reference"
    intent = ShotReferenceIntent(purpose="identity")
    assert CompilerIntent.model_validate_json(intent.model_dump_json()) == intent


def test_shared_full_container_gate_enforces_dependencies():
    command = "python3 scripts/arch_import_scan.py --check"
    # The quality image CMD runs the scan; the workflow must execute that exact
    # image for the exact-source gate (the old dev-only fast jobs were removed
    # because PR CI only listens on main).
    assert command in (ROOT / "backend/Dockerfile.quality").read_text()
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    assert "run_quality_in_docker.ps1 -Stage Full" in workflow
    runner = (ROOT / "scripts/run_quality_in_docker.ps1").read_text()
    backend_run = "docker compose -f docker-compose.quality.yml run --rm --no-deps backend-quality"
    assert backend_run in runner
    assert "scripts/arch_import_scan.py|scripts/architecture-baseline.json" in workflow
