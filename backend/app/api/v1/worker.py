"""Worker-only HTTP tick for local/dev when Arq process is not separate.

This is NOT the user product path. It simulates the Worker process consuming
queued NodeRuns. Production should run `arq app.workers.default.WorkerSettings`.
"""

from __future__ import annotations

from fastapi import APIRouter, Header
from pydantic import BaseModel

from app.api.deps import SessionDep
from app.config import get_settings
from app.runtime.scheduler import WorkerRuntime
from app.shared.errors import ForbiddenError

router = APIRouter(tags=["worker"])


class WorkerTickResponse(BaseModel):
    processed: int
    role: str = "worker"


@router.post("/worker/tick", response_model=WorkerTickResponse)
async def worker_tick(
    session: SessionDep,
    x_worker_token: str | None = Header(default=None, alias="X-Worker-Token"),
) -> WorkerTickResponse:
    """Process queued NodeRuns (Adapter allowed). Requires worker token."""
    settings = get_settings()
    expected = getattr(settings, "worker_token", None) or "dev-worker-token"
    if x_worker_token != expected:
        raise ForbiddenError("worker token required")
    n = await WorkerRuntime(session).process_queued(limit=20)
    return WorkerTickResponse(processed=n)
