"""Structural tests for the container-owned quality entrypoint."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
QUALITY = REPO_ROOT / "scripts" / "run_quality.ps1"


def test_run_quality_script_delegates_to_container_gate() -> None:
    text = QUALITY.read_text(encoding="utf-8")
    assert "run_quality_in_docker.ps1" in text
    assert "@args" in text
    assert "Get-ProjectPython" not in text
    assert "pip install" not in text


def test_container_quality_script_owns_all_project_checks() -> None:
    text = (REPO_ROOT / "scripts" / "run_quality_in_docker.ps1").read_text(
        encoding="utf-8"
    )
    assert "docker compose -f docker-compose.quality.yml build" in text
    assert "backend-quality" in text
    assert "frontend-quality" in text
    assert "litellm-integration-quality" in text


def test_full_gate_keeps_all_checks_in_dependency_order() -> None:
    text = (REPO_ROOT / "scripts" / "run_quality_in_docker.ps1").read_text(
        encoding="utf-8"
    )
    commands = [
        "build backend-quality frontend-quality",
        "up -d postgres-quality redis-quality minio-quality",
        "run --rm --no-deps backend-quality",
        "run --rm --no-deps frontend-quality",
        "--exit-code-from media-resource-quality",
        "--exit-code-from auth-gateway-integration-quality",
        "--exit-code-from litellm-integration-quality",
    ]
    positions = [text.index(command) for command in commands]
    assert positions == sorted(positions)
    assert "finally {" in text
    assert "down --volumes --remove-orphans" in text


def test_ci_and_release_invoke_unfiltered_full_gate() -> None:
    import yaml

    for filename, job in (("ci.yml", "container-gates"), ("release.yml", "verify-release-source")):
        workflow = yaml.safe_load(
            (REPO_ROOT / ".github/workflows" / filename).read_text(encoding="utf-8")
        )
        job_config = workflow["jobs"][job]
        project = job_config["env"]["COMPOSE_PROJECT_NAME"]
        assert project.startswith("df-quality-")
        assert "github.run_id" in project and "github.run_attempt" in project
        steps = job_config["steps"]
        gates = [step for step in steps if "run_quality_in_docker.ps1" in step.get("run", "")]
        assert len(gates) == 1
        assert gates[0]["id"] == "quality"
        assert gates[0]["shell"] == "pwsh"
        assert gates[0]["run"] == "./scripts/run_quality_in_docker.ps1 -Stage Full"
        assert "continue-on-error" not in gates[0]
        # CI cancellation can bypass script finally; retain a runner cleanup fallback.
        assert any(
            step.get("if") == "always() && steps.quality.outputs.cleanup_owned == 'true'"
            and "down --volumes --remove-orphans" in step.get("run", "")
            for step in steps
        )
