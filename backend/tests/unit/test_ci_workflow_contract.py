"""CI contract checks for the canonical frontend quality gates."""

from __future__ import annotations

from pathlib import Path

_WORKFLOW = (
    Path(__file__).resolve().parents[3] / ".github" / "workflows" / "ci.yml"
)


def test_frontend_job_enforces_generated_api_contract_check() -> None:
    workflow = _WORKFLOW.read_text(encoding="utf-8")
    start = workflow.index("\n  frontend:\n")
    end = workflow.index("\n  frontend-smoke:", start)
    frontend_job = workflow[start:end]

    assert "defaults:\n      run:\n        working-directory: frontend" in frontend_job
    assert "- run: npm ci" in frontend_job
    assert "- run: npm run api:check" in frontend_job
    assert frontend_job.index("npm ci") < frontend_job.index("npm run api:check")
