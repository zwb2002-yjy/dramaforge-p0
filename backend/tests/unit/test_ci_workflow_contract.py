"""CI contract checks for the container-only quality gate."""

from __future__ import annotations

import re
from pathlib import Path

_WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "ci.yml"
_SECURITY_WORKFLOW = (
    Path(__file__).resolve().parents[3] / ".github" / "workflows" / "security.yml"
)


def _job(workflow: str, name: str) -> str:
    start = workflow.index(f"\n  {name}:\n")
    next_job = re.search(r"\n  [a-z0-9][a-z0-9-]*:\n", workflow[start + 1 :])
    end = start + 1 + next_job.start() if next_job is not None else len(workflow)
    return workflow[start:end]


def test_container_gate_owns_all_project_toolchains_and_quality_commands() -> None:
    workflow = _WORKFLOW.read_text(encoding="utf-8")
    container_job = _job(workflow, "container-gates")

    assert "docker-compose.quality.yml" in container_job
    assert "docker compose -f docker-compose.quality.yml build" in container_job
    assert "--exit-code-from backend-quality" in container_job
    assert "postgres-quality backend-quality" in container_job
    assert "run --rm --no-deps frontend-quality" in container_job
    assert "litellm-integration-quality" in container_job
    assert "--volumes --remove-orphans" in container_job
    assert "if: always()" in container_job
    assert "actions/setup-python" not in container_job
    assert "actions/setup-node" not in container_job


def test_ci_does_not_install_project_toolchains_on_the_runner() -> None:
    workflow = _WORKFLOW.read_text(encoding="utf-8")
    assert "actions/setup-python" not in workflow
    assert "actions/setup-node" not in workflow
    assert "uv sync" not in workflow
    assert "docker run" in workflow


def test_policy_checks_run_inside_a_python_container() -> None:
    workflow = _WORKFLOW.read_text(encoding="utf-8")
    policy_job = _job(workflow, "policy")
    assert "python:3.12-slim" in policy_job
    assert "scripts/check_directory_compliance.py" in policy_job
    assert "scripts/repo_guardrails.py policy" in policy_job


def test_quality_images_own_browser_and_canonical_surface_gates() -> None:
    backend_dockerfile = (
        Path(__file__).resolve().parents[3] / "backend" / "Dockerfile.quality"
    ).read_text(encoding="utf-8")
    frontend_dockerfile = (
        Path(__file__).resolve().parents[3] / "frontend" / "Dockerfile.quality"
    ).read_text(encoding="utf-8")
    assert "scripts/check_canonical_surface.py" in backend_dockerfile
    assert "uv run --directory backend mypy app" in backend_dockerfile
    assert "chromium" in frontend_dockerfile
    assert "npm run --prefix frontend test:e2e" in frontend_dockerfile


def test_security_workflow_gates_optional_dependency_review_on_repository_capability() -> None:
    workflow = _SECURITY_WORKFLOW.read_text(encoding="utf-8")
    dependency_review = _job(workflow, "dependency-review")

    assert (
        "if: github.event_name == 'pull_request' && "
        "vars.DEPENDENCY_REVIEW_ENABLED == 'true'"
    ) in dependency_review
    assert "fail-on-severity: high" in dependency_review
    assert "continue-on-error:" not in dependency_review

    filesystem_scan = _job(workflow, "filesystem-scan")
    assert "security-events: write" in filesystem_scan
    assert "continue-on-error: true" in filesystem_scan
