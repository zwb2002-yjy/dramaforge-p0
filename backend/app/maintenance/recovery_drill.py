"""Recovery drills over restored state (I10-01).

Restoring rows proves nothing about recovery. These checks read a restored
database and ask what can actually drift, given what the schema already
guarantees:

* a queued run must be re-enqueueable without forking a duplicate (its key must
  be usable — the schema makes it unique per project, not non-blank);
* a ``running`` row must hold a lease a restarted worker can reclaim: it needs a
  timestamp, and it must not sit past the maximum lease;
* an ``unknown_submission`` must not claim a remote id it could never poll,
  because that is the row a resume would trust.

One operation per node run is already a partial unique index, so "two possible
creates" is not a reachable state and is not checked here. Every failure means
"do not resume production traffic yet".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.execution.models import NodeRun, ProviderOperation

# A run may legitimately hold the heavy worker timeout (1800s) plus margin;
# beyond that the lease is stale and a restart must be able to reclaim it.
MAX_RUNNING_LEASE = timedelta(minutes=45)


@dataclass
class DrillReport:
    checks: list[str] = field(default_factory=list)
    failures: list[dict[str, Any]] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.failures

    def fail(self, code: str, detail: str, **extra: Any) -> None:
        self.failures.append({"code": code, "detail": detail, **extra})

    def as_dict(self) -> dict[str, Any]:
        return {"passed": self.passed, "checks": list(self.checks), "failures": self.failures}


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


async def drill_recovery_state(
    session: AsyncSession, *, now: datetime | None = None
) -> DrillReport:
    """Return every recovery readiness problem, not just the first."""
    moment = now or datetime.now(UTC)
    report = DrillReport()

    report.checks.append("queue_idempotency")
    queued = list((await session.scalars(select(NodeRun).where(NodeRun.status == "queued"))).all())
    for run in queued:
        if not (run.idempotency_key or "").strip():
            report.fail(
                "DRILL_QUEUE_KEY_MISSING",
                "queued run cannot be re-enqueued idempotently",
                node_run_id=str(run.id),
            )

    report.checks.append("running_lease")
    running = list(
        (await session.scalars(select(NodeRun).where(NodeRun.status == "running"))).all()
    )
    for run in running:
        if run.started_at is None:
            report.fail(
                "DRILL_ORPHANED_RUNNING",
                "running run has no lease timestamp",
                node_run_id=str(run.id),
            )
            continue
        if moment - _aware(run.started_at) > MAX_RUNNING_LEASE:
            report.fail(
                "DRILL_STALE_LEASE",
                "running run exceeded the maximum lease and would not be reclaimed",
                node_run_id=str(run.id),
            )

    report.checks.append("unknown_submission_identity")
    unknown = list(
        (
            await session.scalars(
                select(ProviderOperation).where(ProviderOperation.status == "unknown_submission")
            )
        ).all()
    )
    for operation in unknown:
        if operation.provider_operation_id:
            report.fail(
                "DRILL_UNKNOWN_WITHOUT_REMOTE_ID",
                "unknown submission claims a remote id it cannot have polled",
                provider_operation_id=str(operation.id),
                node_run_id=str(operation.node_run_id),
            )
    return report


__all__ = ["MAX_RUNNING_LEASE", "DrillReport", "drill_recovery_state"]
