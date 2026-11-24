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


def test_institution_business_processes_have_no_external_network_or_credentials() -> None:
    """An inherited Compose change must not expose the real-API fixture to providers."""
    import yaml

    compose = yaml.safe_load((REPO_ROOT / "docker-compose.quality.yml").read_text())
    services = compose["services"]
    assert compose["networks"]["institution-quality"]["internal"] is True
    institution = {
        name: value for name, value in services.items() if name.startswith("institution-")
    }
    assert len(institution) >= 8
    for name, service in institution.items():
        assert service["networks"] == ["institution-quality"], name
        assert not service.get("ports"), name
        assert not service.get("network_mode"), name
        assert not service.get("env_file"), name
        assert not service.get("privileged"), name
        assert not service.get("extra_hosts"), name
        for mount in service.get("volumes", []):
            assert "/playwright-results:" in mount, (name, mount)
        for key, value in service.get("environment", {}).items():
            assert "${" not in str(value), (name, key)
    for name in (
        "institution-api-quality", "institution-dispatcher-quality",
        "institution-worker-default-quality", "institution-worker-director-quality",
        "institution-worker-heavy-quality",
    ):
        environment = services[name]["environment"]
        assert "dramaforge_app:" in environment["DATABASE_URL"]
        assert environment["DATABASE_URL"].endswith("/dramaforge_institution")
        assert environment["REDIS_URL"].endswith("/14")
        assert environment["MINIO_BUCKET"] == "quality-institution"
        assert environment["APP_ENV"] != "test"  # Exercise the real SSE bridge.
        assert environment["LITELLM_GATEWAY_URL"] == ""
