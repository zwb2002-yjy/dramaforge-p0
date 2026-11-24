"""Physical dispatch metadata, separate from a NodeRun's frozen execution input."""

import math
from datetime import UTC, datetime

from sqlalchemy import and_, or_
from sqlalchemy.sql.elements import ColumnElement

from app.execution.models import NodeRun


def due_node_runs(now: datetime) -> ColumnElement[bool]:
    return and_(
        or_(
            NodeRun.status == "queued",
            and_(
                NodeRun.status == "cancel_requested",
                NodeRun.started_at.is_(None),
            ),
        ),
        or_(NodeRun.next_attempt_at.is_(None), NodeRun.next_attempt_at <= now),
    )


def node_run_is_due(run: NodeRun, *, now: datetime) -> bool:
    due = run.next_attempt_at
    return due is None or due.replace(tzinfo=due.tzinfo or UTC) <= now


def provider_retry_delay(value: object, *, now: datetime) -> float:
    seconds = float(value) if isinstance(value, int | float) else 5.0
    if not math.isfinite(seconds) or seconds <= 0:
        seconds = 5.0
    return min(max(seconds, 1.0), (datetime.max.replace(tzinfo=UTC) - now).total_seconds() - 1)


def node_run_dispatch_generation(run: NodeRun) -> str:
    original = str((run.input_snapshot or {}).get("dispatch_generation") or "")
    sequence = (run.output_summary or {}).get("provider_poll_sequence")
    if isinstance(sequence, int) and sequence > 0:
        return f"{original}:poll-{sequence}"
    return original
