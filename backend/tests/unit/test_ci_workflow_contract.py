"""CI contract checks for the canonical API and frontend quality gates."""

from __future__ import annotations

import re
from pathlib import Path

_WORKFLOW = (
    Path(__file__).resolve().parents[3] / ".github" / "workflows" / "ci.yml"
)
_SECURITY_WORKFLOW = (
    Path(__file__).resolve().parents[3] / ".github" / "workflows" / "security.yml"
)


def _job(workflow: str, name: str) -> str:
    start = workflow.index(f"\n  {name}:\n")
    next_job = re.search(r"\n  [a-z0-9][a-z0-9-]*:\n", workflow[start + 1 :])
    end = start + 1 + next_job.start() if next_job is not None else len(workflow)
    return workflow[start:end]


def _step(job: str, marker: str) -> str:
    start = job.index(f"      - {marker}")
    next_step = job.find("\n      - ", start + 1)
    end = next_step if next_step != -1 else len(job)
    return job[start:end]


def test_api_contract_job_owns_generated_api_contract_check() -> None:
    workflow = _WORKFLOW.read_text(encoding="utf-8")
    api_job = _job(workflow, "api-contract")

    # This is a standalone required job; it must not inherit an unrelated job
    # dependency or be made advisory by a conditional/error-tolerant step.
    assert "needs:" not in api_job
    assert "continue-on-error:" not in api_job
    assert "if:" not in api_job
    assert "uses: actions/setup-python@v5" in api_job
    assert 'python-version: "3.12"' in api_job
    assert "uses: astral-sh/setup-uv@v6" in api_job
    assert "working-directory: backend" in api_job
    assert "uv sync --locked --extra dev" in api_job
    assert "uses: actions/setup-node@v4" in api_job
    assert 'node-version: "22"' in api_job
    assert "working-directory: frontend" in api_job
    assert "- run: npm ci" in api_job
    assert "- name: Check generated API contract" in api_job
    assert "run: npm run api:check" in api_job
    backend_sync = _step(api_job, "name: Sync backend dependencies")
    frontend_install = _step(api_job, "run: npm ci")
    api_check = _step(api_job, "name: Check generated API contract")
    assert "working-directory: backend" in backend_sync
    assert "working-directory: frontend" in frontend_install
    assert "working-directory: frontend" in api_check
    assert api_job.index("actions/checkout@v4") < api_job.index("actions/setup-python@v5")
    assert api_job.index("actions/setup-python@v5") < api_job.index("astral-sh/setup-uv@v6")
    assert api_job.index("astral-sh/setup-uv@v6") < api_job.index(
        "uv sync --locked --extra dev"
    )
    assert api_job.index("uv sync --locked --extra dev") < api_job.index(
        "actions/setup-node@v4"
    )
    assert api_job.index("actions/setup-node@v4") < api_job.index("npm ci")
    assert api_job.index("uv sync --locked --extra dev") < api_job.index("npm ci")
    assert api_job.index("npm ci") < api_job.index("npm run api:check")
    assert api_job.count("npm run api:check") == 1


def test_frontend_job_keeps_only_frontend_quality_gates() -> None:
    workflow = _WORKFLOW.read_text(encoding="utf-8")
    frontend_job = _job(workflow, "frontend")

    assert "defaults:\n      run:\n        working-directory: frontend" in frontend_job
    assert "- run: npm ci" in frontend_job
    assert "npm run api:check" not in frontend_job
    for command in ("lint", "typecheck", "test", "build"):
        assert f"- run: npm run {command}" in frontend_job


def test_postgres_integration_job_checks_schema_before_integration_tests() -> None:
    workflow = _WORKFLOW.read_text(encoding="utf-8")
    postgres_job = _job(workflow, "postgres-integration")

    assert "image: postgres:15" in postgres_job
    assert "- run: uv run alembic upgrade head" in postgres_job
    assert "- run: uv run alembic check" in postgres_job
    assert "- run: uv run pytest tests/integration -q -rs --fail-on-skip" in postgres_job

    # Schema drift and integration failures are required gates.  Do not make
    # either command advisory or conditionally skippable.
    assert "continue-on-error:" not in postgres_job
    assert "if:" not in postgres_job
    assert "skip: true" not in postgres_job
    assert "|| true" not in postgres_job

    upgrade = postgres_job.index("uv run alembic upgrade head")
    schema_check = postgres_job.index("uv run alembic check")
    integration = postgres_job.index(
        "uv run pytest tests/integration -q -rs --fail-on-skip"
    )
    assert upgrade < schema_check < integration


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
