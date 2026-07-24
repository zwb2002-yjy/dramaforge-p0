"""Worker entrypoint smoke tests (no Redis required)."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.config import clear_settings_cache
from app.execution.models import NodeRun
from app.shared.errors import ValidationAppError
from app.workers.jobs import execute_node_run
from app.workers.main import describe_worker, main
from arq import Retry


def test_describe_worker_default() -> None:
    line = describe_worker("default")
    assert "kind=default" in line
    assert "status=ready" in line


def test_describe_worker_heavy() -> None:
    line = describe_worker("heavy")
    assert "kind=heavy" in line
    assert "status=ready" in line


def test_heavy_worker_reads_concurrency_from_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARQ_HEAVY_MAX_JOBS", "4")
    clear_settings_cache()
    from app.workers import heavy

    assert heavy.WorkerSettings.max_jobs == 4
    assert heavy.WorkerSettings.max_tries == 400
    clear_settings_cache()


def test_main_unknown_kind() -> None:
    assert main(["unknown"]) == 2


def test_main_default_ok() -> None:
    assert main(["default"]) == 0


class _FakeSession:
    def __init__(self, run: NodeRun) -> None:
        self.run = run
        self.commits = 0
        self.rollbacks = 0

    async def get(self, model: object, ident: object) -> NodeRun | None:
        _ = model
        return self.run if ident == self.run.id else None

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class _SessionContext(AbstractAsyncContextManager[_FakeSession]):
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    async def __aenter__(self) -> _FakeSession:
        return self._session

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        return None


@pytest.mark.asyncio
async def test_worker_persists_unhandled_provider_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = NodeRun(
        id=uuid4(),
        project_id=uuid4(),
        graph_version_id=uuid4(),
        graph_node_id=uuid4(),
        idempotency_key=f"worker:{uuid4()}",
        input_hash="a" * 64,
        status="queued",
        input_snapshot={},
        created_by=uuid4(),
    )
    first = _FakeSession(run)
    fallback = _FakeSession(run)
    sessions = iter([first, fallback])

    def factory() -> _SessionContext:
        return _SessionContext(next(sessions))

    async def no_rls(*args: object, **kwargs: object) -> None:
        _ = args, kwargs

    async def claim(*args: object, **kwargs: object) -> NodeRun:
        _ = args, kwargs
        run.status = "running"
        return run

    async def fail(*args: object, **kwargs: object) -> object:
        _ = args, kwargs
        raise ValidationAppError("PROVIDER_FAILED: hub overloaded")

    monkeypatch.setattr("app.workers.jobs.get_session_factory", lambda: factory)
    monkeypatch.setattr("app.workers.jobs.set_rls_context", no_rls)
    monkeypatch.setattr("app.execution.product_path.claim_media_node_run", claim)
    monkeypatch.setattr("app.execution.product_path.execute_media_node_run", fail)

    result = await execute_node_run({}, str(run.id))

    assert result["status"] == "failed"
    assert first.rollbacks == 1
    assert fallback.commits == 1
    assert run.status == "failed"
    assert run.error_code == "PROVIDER_FAILED"
    assert run.error_summary == "PROVIDER_FAILED: hub overloaded"
    assert run.finished_at is not None
    assert run.finished_at <= datetime.now(UTC)
    assert run.output_summary == {
        "status": "failed",
        "error_code": "PROVIDER_FAILED",
        "worker_boundary": True,
    }


@pytest.mark.asyncio
async def test_worker_retries_composite_while_source_media_is_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = NodeRun(
        id=uuid4(),
        project_id=uuid4(),
        graph_version_id=uuid4(),
        graph_node_id=uuid4(),
        idempotency_key=f"worker:{uuid4()}",
        input_hash="a" * 64,
        status="queued",
        input_snapshot={"shot_id": str(uuid4()), "node_key": "composite"},
        created_by=uuid4(),
    )
    first = _FakeSession(run)

    def factory() -> _SessionContext:
        return _SessionContext(first)

    async def no_rls(*args: object, **kwargs: object) -> None:
        _ = args, kwargs

    async def pending(*args: object, **kwargs: object) -> bool:
        _ = args, kwargs
        return True

    async def claim(*args: object, **kwargs: object) -> NodeRun:
        raise AssertionError("pending composite must not be claimed")

    monkeypatch.setattr("app.workers.jobs.get_session_factory", lambda: factory)
    monkeypatch.setattr("app.workers.jobs.set_rls_context", no_rls)
    monkeypatch.setattr("app.execution.composite_media.composite_inputs_pending", pending)
    monkeypatch.setattr("app.execution.product_path.claim_media_node_run", claim)

    with pytest.raises(Retry):
        await execute_node_run({}, str(run.id))

    assert first.rollbacks == 1
    assert first.commits == 0
    assert run.status == "queued"
