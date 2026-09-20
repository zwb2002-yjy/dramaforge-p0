"""CI contract checks for the container-only quality gate."""

from __future__ import annotations

import os
import re
import subprocess
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


def _step(workflow: str, name: str) -> dict[str, str]:
    import yaml

    parsed = yaml.safe_load(workflow)
    return next(
        step for step in parsed["jobs"]["policy"]["steps"] if step.get("name") == name
    )


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


def test_branch_flow_admits_dependency_integration_but_protects_main() -> None:
    step = _step(
        _WORKFLOW.read_text(encoding="utf-8"), "Enforce integration branch flow"
    )
    for base, head, allowed in [
        ("dev", "dependabot/npm_and_yarn/frontend/prettier-3.9.6", True),
        ("dev", "agent/runtime-policy", True),
        ("dev", "codex/workbench-optimization", True),
        ("main", "codex/workbench-optimization", False),
        ("dev", "unreviewed-feature", False),
        ("main", "dependabot/npm_and_yarn/frontend/prettier-3.9.6", False),
        ("main", "dev", True),
    ]:
        result = subprocess.run(
            ["bash", "-c", step["run"]],
            env={"BASE_REF": base, "HEAD_REF": head},
            capture_output=True,
            text=True,
            check=False,
        )
        assert (result.returncode == 0) == allowed, result.stdout + result.stderr


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


def test_quality_images_cache_dependencies_before_copying_source() -> None:
    backend = (
        Path(__file__).resolve().parents[3] / "backend" / "Dockerfile.quality"
    ).read_text(encoding="utf-8")
    frontend = (
        Path(__file__).resolve().parents[3] / "frontend" / "Dockerfile.quality"
    ).read_text(encoding="utf-8")

    backend_dependencies = "COPY backend/pyproject.toml backend/uv.lock backend/README.md"
    assert backend.index(backend_dependencies) < backend.index("COPY . .")
    assert backend.index("COPY . .") < backend.rindex("RUN uv sync")
    assert frontend.index("COPY frontend/package.json") < frontend.index("COPY . .")
    assert frontend.index("RUN npm ci") < frontend.index("COPY . .")


def test_main_pr_preserves_every_required_check_context() -> None:
    workflow = _WORKFLOW.read_text(encoding="utf-8")
    required = (
        "policy",
        "container-gates",
        "secret-scan",
        "python-dependencies",
        "frontend-dependencies",
        "filesystem-scan",
    )

    for name in required:
        assert f"name: {name}" in _job(workflow, name)
    for name in required[1:2] + required[3:]:
        assert "github.base_ref == 'main'" in _job(workflow, name)


def test_changed_path_classifier_routes_fast_and_full_gates(tmp_path: Path) -> None:
    step = _step(_WORKFLOW.read_text(encoding="utf-8"), "Classify changed paths")
    cases = {
        "docs": (["docs/guide.md"], {"docs_only": "true", "full_quality": "false"}),
        "backend": (
            ["backend/app/shared/json.py"],
            {"backend": "true", "full_quality": "false"},
        ),
        "frontend": (
            ["frontend/src/lib/api.ts"],
            {"frontend": "true", "full_quality": "false"},
        ),
        "migration": (
            ["backend/alembic/versions/new.py"],
            {"migrations": "true", "full_quality": "true"},
        ),
        "generated-api": (
            ["frontend/src/shared/api/generated.ts"],
            {"api_contract": "true", "full_quality": "true"},
        ),
        "script": (
            ["scripts/prove_new_flow.py"],
            {"backend": "true", "full_quality": "false"},
        ),
        "cross-stack": (
            ["backend/tests/unit/test_x.py", "frontend/tests/unit/x.test.ts"],
            {"full_quality": "true"},
        ),
        "workflow": (
            [".github/workflows/ci.yml"],
            {"infra": "true", "full_quality": "true"},
        ),
    }

    for case_name, (paths, expected) in cases.items():
        repo = tmp_path / case_name
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "CI Test"], cwd=repo, check=True)
        subprocess.run(
            ["git", "config", "user.email", "ci@example.invalid"], cwd=repo, check=True
        )
        (repo / ".baseline").write_text("baseline\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "baseline"], cwd=repo, check=True)
        base_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repo, text=True
        ).strip()

        for relative in paths:
            target = repo / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("changed\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "change"], cwd=repo, check=True)
        head_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repo, text=True
        ).strip()

        output = repo / "github-output"
        result = subprocess.run(
            ["bash", "-c", step["run"]],
            cwd=repo,
            env={
                **os.environ,
                "EVENT_NAME": "pull_request",
                "BASE_SHA": base_sha,
                "HEAD_SHA": head_sha,
                "GITHUB_OUTPUT": str(output),
            },
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        actual = dict(
            line.split("=", 1)
            for line in output.read_text(encoding="utf-8").splitlines()
        )
        for name, value in expected.items():
            assert actual[name] == value, case_name


def test_ci_gates_optional_dependency_review_on_repository_capability() -> None:
    workflow = _WORKFLOW.read_text(encoding="utf-8")
    dependency_review = _job(workflow, "dependency-review")

    assert "vars.DEPENDENCY_REVIEW_ENABLED == 'true'" in dependency_review
    assert "fail-on-severity: high" in dependency_review
    assert "continue-on-error:" not in dependency_review

    filesystem_scan = _job(workflow, "filesystem-scan")
    assert "security-events: write" in filesystem_scan
    assert "continue-on-error: true" in filesystem_scan


def test_scheduled_security_workflow_has_no_pr_or_push_duplication() -> None:
    workflow = _SECURITY_WORKFLOW.read_text(encoding="utf-8")

    assert "  pull_request:" not in workflow
    assert "  push:" not in workflow
    assert "  schedule:" in workflow
    assert "  workflow_dispatch:" in workflow
    for job in (
        "scheduled-secret-scan",
        "scheduled-python-dependencies",
        "scheduled-frontend-dependencies",
        "scheduled-filesystem-scan",
    ):
        assert _job(workflow, job)
