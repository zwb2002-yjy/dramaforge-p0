"""CI/Release selection contracts; shell behavior is tested by the native lifecycle suite."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
# Execution order, failures and resource ownership are exercised by the native shell suite.


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
        assert any(
            step.get("shell") == "pwsh"
            and step.get("run") == "./backend/tests/unit/test_quality_output_lifecycle.ps1"
            for step in steps
        )
        gates = [step for step in steps if "run_quality_in_docker.ps1" in step.get("run", "")]
        assert len(gates) == 1
        assert gates[0]["id"] == "quality"
        assert gates[0]["shell"] == "pwsh"
        expected = "./scripts/run_quality_in_docker.ps1 -Stage Full"
        if filename == "release.yml":
            expected += " -KeepArtifacts"
        assert gates[0]["run"] == expected
        assert "continue-on-error" not in gates[0]
        # CI cancellation can bypass script finally; retain a runner cleanup fallback.
        assert any(
            step.get("if") == "always() && steps.quality.outputs.cleanup_owned == 'true'"
            and "down --volumes --remove-orphans" in step.get("run", "")
            for step in steps
        )
