"""Qualified production cancellation; workers retain the frozen remote identity."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project
from app.execution.models import NodeRun, ProviderOperation
from app.shared.errors import ConflictError, NotFoundError


class ProductionRunControl:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def request_cancel(self, *, project: Project, run_id: UUID) -> NodeRun:
        run = await self._session.scalar(
            select(NodeRun)
            .where(
                NodeRun.id == run_id,
                NodeRun.project_id == project.id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if run is None:
            raise NotFoundError("production run not found")
        if run.status in {"cancel_requested", "cancelled", "completed_after_cancel"}:
            return run
        if run.status not in {"queued", "running"}:
            raise ConflictError("production run is not cancellable in its current state")
        run.cancellation_requested_at = datetime.now(UTC)
        submitted = await self._session.scalar(
            select(ProviderOperation.id)
            .where(
                ProviderOperation.node_run_id == run.id,
                ProviderOperation.status.in_(
                    {
                        "submission_started",
                        "unknown_submission",
                        "submitted",
                        "running",
                        "timed_out",
                        "cancel_requested",
                    }
                ),
            )
            .limit(1)
        )
        if run.status == "queued" and submitted is None:
            run.status = "cancelled"
            run.finished_at = run.cancellation_requested_at
            run.output_summary = {
                "status": "cancelled",
                "cancelled_before_submission": True,
            }
        else:
            run.status = "cancel_requested"
        await self._session.flush()
        return run
