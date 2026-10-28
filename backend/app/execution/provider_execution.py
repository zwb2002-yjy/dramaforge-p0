"""Binding-driven Provider submission, recovery, cancellation and result persistence."""

from __future__ import annotations

import asyncio
import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project
from app.config import get_settings
from app.consistency.identity_policy import (
    identity_evidence_policy_snapshot,
)
from app.events.models import OutboxEvent
from app.execution.artifact_lineage import get_or_create_artifact
from app.execution.media_io import (
    _apply_media_metadata,
    _detected_media_format,
    _inspect_media_metadata,
    _mime_for_node,
    _resolve_media_file,
    _validate_provider_media,
)
from app.execution.media_submission import prepare_media_submission
from app.execution.models import Artifact, GraphNode, NodeRun, ProviderOperation
from app.execution.run_state import (
    UNIFIED_PATH_VERSION,
    ExecuteNodeResult,
    _commit_terminal_failure,
)
from app.execution.scheduling import node_run_dispatch_generation
from app.providers.runtime import PROVIDER_CONTENT_URI, require_resume_token_identity
from app.shared.db import set_node_run_rls_context
from app.shared.errors import (
    NodeRunAlreadyClaimedError,
    ProviderTaskCancelledError,
    ProviderTaskPendingError,
    ValidationAppError,
)
from app.storage.minio_store import ObjectStore
from app.storage.scratch import OwnedMediaDirectory

POLL_OBSERVATION_TIMEOUT_SECONDS = 30.0
MAX_POLL_ERROR_BACKOFF_SECONDS = 300.0


def _counter(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValidationAppError("Invalid persisted poll sequence")
    return value


def _same_attempt(first: datetime | None, second: datetime | None) -> bool:
    def utc(value: datetime | None) -> datetime | None:
        return value.replace(tzinfo=value.tzinfo or UTC) if value is not None else None

    return utc(first) == utc(second)


async def _defer_remote_poll(
    session: AsyncSession,
    *,
    run: NodeRun,
    operation: ProviderOperation,
    delay_seconds: float,
    expected_started_at: datetime | None,
) -> None:
    """Release the attempt and schedule the same remote identity atomically."""
    await session.refresh(run, with_for_update=True)
    if not _same_attempt(run.started_at, expected_started_at):
        raise NodeRunAlreadyClaimedError()
    now = datetime.now(UTC)
    # Preserve Retry-After, even when longer than our normal error backoff.
    # Saturation at the largest representable date prevents overflow; it never
    # turns an extreme Provider wait into a burst of premature observations.
    maximum_delay = (datetime.max.replace(tzinfo=UTC) - now).total_seconds() - 1
    due = now + timedelta(seconds=min(delay_seconds, maximum_delay))
    sequence = _counter((run.output_summary or {}).get("provider_poll_sequence", 0)) + 1
    run.status = "cancel_requested" if _cancellation_requested(run) else "queued"
    run.started_at = None
    run.next_attempt_at = due
    run.error_code = "PROVIDER_TASK_PENDING"
    run.error_summary = "Remote Provider task is still running"
    run.output_summary = {
        "status": "provider_pending",
        "provider_operation_id": str(operation.id),
        "provider_poll_sequence": sequence,
        "next_attempt_at": due.isoformat(),
    }
    session.add(
        OutboxEvent(
            event_id=uuid4(),
            project_id=run.project_id,
            topic="node_run.enqueue",
            schema_version=1,
            payload={
                "node_run_id": str(run.id),
                "project_id": str(run.project_id),
                "status": run.status,
                "dispatch_generation": node_run_dispatch_generation(run),
            },
            next_attempt_at=due,
        )
    )
    await session.commit()
    raise ProviderTaskPendingError()


def _unknown_submission_error_summary(transport_error: object = None) -> str:
    summary = "Provider submission outcome is unknown; manual reconciliation required"
    candidate = str(transport_error or "").strip()
    safe = candidate.replace("_", "").replace(".", "")
    if candidate and len(candidate) <= 80 and candidate.isascii() and safe.isalnum():
        return f"{summary} (transport={candidate})"
    return summary


def _cancellation_requested(run: NodeRun) -> bool:
    return run.cancellation_requested_at is not None or run.status == "cancel_requested"


async def _commit_provider_cancelled(
    session: AsyncSession,
    *,
    run: NodeRun,
    operation: ProviderOperation,
    reason: str,
) -> None:
    """Persist a confirmed remote cancellation before leaving the Worker."""
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    operation.status = "cancelled"
    operation.error_code = None
    operation.error_summary = None
    operation.completed_at = now
    summary = dict(operation.response_summary or {})
    summary.update({"cancel_result_status": "cancelled", "cancel_reason": reason})
    operation.response_summary = summary
    run.status = "cancelled"
    run.error_code = None
    run.error_summary = None
    run.finished_at = now
    run.output_summary = {
        "status": "cancelled",
        "provider_operation_id": str(operation.id),
        "reason": reason,
    }
    await session.flush()
    await session.commit()
    await set_node_run_rls_context(session, node_run_id=run.id)


async def _request_remote_cancellation_once(
    session: AsyncSession,
    *,
    run: NodeRun,
    operation: ProviderOperation,
    runtime: object,
    resume: object,
) -> tuple[bool, bool]:
    """Observe cancellation and issue at most one remote cancel request.

    The durable marker is committed before I/O. If the process dies after the
    request, recovery polls the existing remote id and never repeats cancel or
    create. The second return value means the Provider confirmed terminal
    cancellation; otherwise the caller keeps polling the same task.
    """
    from datetime import UTC, datetime

    await session.refresh(run)
    requested = _cancellation_requested(run)
    if not requested:
        return False, False
    summary = dict(operation.response_summary or {})
    if summary.get("cancel_result_status") == "cancelled":
        return True, True
    if operation.cancel_requested_at is not None:
        return True, False

    summary["cancel_request_state"] = "started"
    claimed = await session.scalar(
        update(ProviderOperation)
        .where(
            ProviderOperation.id == operation.id,
            ProviderOperation.cancel_requested_at.is_(None),
        )
        .values(
            status="cancel_requested",
            cancel_requested_at=datetime.now(UTC),
            response_summary=summary,
        )
        .returning(ProviderOperation.id)
        .execution_options(synchronize_session=False)
    )
    await session.refresh(operation)
    if claimed is None:
        return True, (operation.response_summary or {}).get("cancel_result_status") == "cancelled"
    await session.commit()
    await set_node_run_rls_context(session, node_run_id=run.id)
    try:
        cancel = await runtime.cancel_video(resume)  # type: ignore[attr-defined]
        cancel_status = str(getattr(cancel, "status", "unknown"))
    except Exception as exc:  # noqa: BLE001 - polling remains authoritative
        cancel_status = "error"
        summary = dict(operation.response_summary or {})
        summary["cancel_error_class"] = type(exc).__name__[:120]
    else:
        summary = dict(operation.response_summary or {})
    summary["cancel_request_state"] = "completed"
    summary["cancel_result_status"] = cancel_status[:80]
    operation.response_summary = summary
    await session.commit()
    await set_node_run_rls_context(session, node_run_id=run.id)
    return True, cancel_status == "cancelled"


async def _execute_unified_media_node_run(
    session: AsyncSession,
    *,
    run: NodeRun,
    node: GraphNode,
    node_type: str,
    snap: dict[str, object],
    obj_store: ObjectStore,
    prompt: str,
    canonical_image_bytes: bytes | None,
    lead_identity_required: bool,
    has_canonical_binding: bool,
    canonical_artifact: Artifact | None = None,
) -> ExecuteNodeResult:
    """Stage B4: binding-driven unified execution path.

    Single-path submission: a persisted ``execution_path_version`` wins over any
    flag; resume never re-creates a remote task; ``submission_started`` without a
    remote id (crash between commit and response) is escalated to
    ``unknown_submission`` for manual reconciliation instead of a duplicate POST.
    """
    from datetime import UTC, datetime

    from app.production.execution_plan import WorkbenchExecutionPlan
    from app.providers.execution_identity import (
        ExecutionIdentitySnapshot,
    )
    from app.providers.runtime import (
        CompiledImageRequest,
        CostResult,
        PollResult,
        ProviderResumeToken,
        ProviderRuntime,
        ProviderRuntimeResolver,
        SubmissionResult,
    )
    from app.shared.errors import ProviderRateLimitedError

    now = datetime.now(UTC)
    attempt_started_at = run.started_at
    project = await session.scalar(select(Project).where(Project.id == run.project_id))
    if project is None:
        raise ValidationAppError("project not found for node run")
    if await set_node_run_rls_context(session, node_run_id=run.id) is None:
        raise ValidationAppError("node_run ownership context unavailable")

    op = await session.scalar(
        select(ProviderOperation)
        .where(
            ProviderOperation.node_run_id == run.id,
            ProviderOperation.execution_path_version == UNIFIED_PATH_VERSION,
        )
        .order_by(ProviderOperation.attempt_no.desc(), ProviderOperation.created_at.desc())
        .limit(1)
    )
    frozen_identity: ExecutionIdentitySnapshot | None = None
    operation_identity = (
        op.selection_plan.get("execution_identity")
        if op is not None and isinstance(op.selection_plan, dict)
        else None
    )
    request_identity = (
        op.request_summary.get("execution_identity")
        if op is not None and isinstance(op.request_summary, dict)
        else None
    )
    run_identity = snap.get("execution_identity")
    persisted_identities = [
        value for value in (operation_identity, request_identity, run_identity) if value is not None
    ]
    if persisted_identities and any(
        value != persisted_identities[0] for value in persisted_identities[1:]
    ):
        raise ValidationAppError(
            "persisted execution identity evidence differs across run records",
            details={"code": "EXECUTION_IDENTITY_MISMATCH"},
        )
    raw_identity = operation_identity if operation_identity is not None else run_identity
    if op is not None and operation_identity is not None and request_identity is None:
        raise ValidationAppError(
            "ProviderOperation execution identity evidence is incomplete",
            details={"code": "EXECUTION_IDENTITY_INVALID"},
        )
    if raw_identity is not None:
        if not isinstance(raw_identity, dict):
            raise ValidationAppError(
                "persisted execution identity is malformed",
                details={"code": "EXECUTION_IDENTITY_INVALID"},
            )
        try:
            frozen_identity = ExecutionIdentitySnapshot.model_validate(raw_identity)
        except ValueError as exc:
            raise ValidationAppError(
                "persisted execution identity is invalid",
                details={"code": "EXECUTION_IDENTITY_INVALID"},
            ) from exc

    # Workbench NodeRuns persist a frozen P4 plan before a ProviderOperation is
    # created.  Parse it once at the worker boundary so execution can consume
    # that exact ExecutionModelResolution rather than asking the selection
    # service to choose from mutable profile state again.
    raw_workbench_plan = snap.get("workbench_plan")
    workbench_plan: WorkbenchExecutionPlan | None = None
    if raw_workbench_plan is not None:
        if not isinstance(raw_workbench_plan, dict):
            raise ValidationAppError(
                "professional workbench plan is malformed",
                details={"code": "EXECUTION_PLAN_INVALID"},
            )
        try:
            workbench_plan = WorkbenchExecutionPlan.model_validate(raw_workbench_plan)
        except ValueError as exc:
            raise ValidationAppError(
                "professional workbench plan is invalid",
                details={"code": "EXECUTION_PLAN_INVALID"},
            ) from exc

    create_status = "created"
    remote = ""
    runtime: ProviderRuntime | None = None
    resume: ProviderResumeToken | None = None
    synchronous_image = False
    result: SubmissionResult | None = None

    resubmit = bool(op is not None and op.status == "rejected" and not op.provider_operation_id)
    if op is not None and not resubmit:
        if op.status == "unknown_submission":
            raise ValidationAppError(
                "提交结果未知，必须人工核对，不能自动重发",
                details={"code": "PROVIDER_SUBMISSION_UNKNOWN"},
            )
        # A crash between the submission_started commit and the remote-id write
        # leaves an op with no remote id. Its outcome is unknown; escalate to
        # manual reconciliation instead of risking a duplicate POST.
        if op.status == "submission_started" and not op.provider_operation_id:
            op.status = "unknown_submission"
            op.error_code = "PROVIDER_SUBMISSION_UNKNOWN"
            op.error_summary = (
                "submission_started with no remote id: outcome unknown; "
                "manual reconciliation required"
            )
            op.completed_at = now
            await _commit_terminal_failure(
                session,
                run=run,
                error_code="PROVIDER_SUBMISSION_UNKNOWN",
                error_summary=op.error_summary,
            )
            raise ValidationAppError("PROVIDER_SUBMISSION_UNKNOWN")
        if frozen_identity is None:
            raise ValidationAppError(
                "历史任务缺少已冻结的执行身份，必须人工核对，不能使用当前连接恢复",
                details={"code": "EXECUTION_IDENTITY_MISSING"},
            )
        try:
            resume = ProviderResumeToken.model_validate(op.resume_token)
        except ValueError as exc:
            raise ValidationAppError(
                "已提交任务缺少有效恢复令牌", details={"code": "RESUME_TOKEN_UNAVAILABLE"}
            ) from exc
        require_resume_token_identity(
            resume,
            remote_task_id=op.provider_operation_id,
            provider_type=op.actual_provider,
            protocol_profile=op.protocol_profile,
            remote_secondary_id=op.remote_secondary_id,
        )
        # Resume only. Never create a second remote task. Rebuild the runtime
        # exclusively from the persisted execution identity.
        runtime = await ProviderRuntimeResolver(session).resume_runtime_for_identity(
            identity=frozen_identity,
            workspace_id=project.workspace_id,
            operation=op,
        )
        remote = str(op.provider_operation_id or "")
        create_status = "resumed"

    if op is None or resubmit:
        # New submission. Resolve via the shared selection engine.
        prepared = await prepare_media_submission(
            session,
            project=project,
            run=run,
            node_type=node_type,
            snap=snap,
            obj_store=obj_store,
            prompt=prompt,
            canonical_image_bytes=canonical_image_bytes,
            has_canonical_binding=has_canonical_binding,
            canonical_artifact=canonical_artifact,
            frozen_identity=frozen_identity,
            workbench_plan=workbench_plan,
            op=op,
            now=now,
        )
        op = prepared.operation
        compiled = prepared.compiled
        runtime = prepared.runtime
        identity_json = prepared.identity_json

        # A user cancellation that committed while the request was being
        # compiled wins before the paid boundary. The submission marker proves
        # no Provider call has happened yet, so this cancellation is terminal
        # without remote I/O.
        await session.refresh(run)
        if _cancellation_requested(run):
            await _commit_provider_cancelled(
                session,
                run=run,
                operation=op,
                reason="cancelled_before_provider_submission",
            )
            raise ProviderTaskCancelledError()

        if isinstance(compiled, CompiledImageRequest):
            result = await runtime.submit_image(compiled)
        else:
            result = await runtime.submit_video(compiled)
        if result.status == "unknown_submission":
            op.status = "unknown_submission"
            op.error_code = str(result.error_code or "PROVIDER_SUBMISSION_UNKNOWN")
            op.error_summary = _unknown_submission_error_summary(result.error)
            op.completed_at = datetime.now(UTC)
            await _commit_terminal_failure(
                session,
                run=run,
                error_code="PROVIDER_SUBMISSION_UNKNOWN",
                error_summary=op.error_summary,
            )
            raise ValidationAppError("PROVIDER_SUBMISSION_UNKNOWN")
        if result.status in {"failed", "error", "cancelled"}:
            error_text = str(result.error or "provider rejected task creation")[:500]
            if result.error_code == "PROVIDER_RATE_LIMITED":
                raw_retry_after = getattr(result, "retry_after_seconds", None)
                try:
                    retry_after = float(raw_retry_after) if raw_retry_after else 5.0
                except (TypeError, ValueError):
                    retry_after = 5.0
                # The provider explicitly refused with 429 and did not create a
                # remote task. Mark the op rejected and COMMIT so a worker
                # rollback cannot leave it dangling as submission_started; the
                # scheduler requeues the run and the retry resubmits.
                op.status = "rejected"
                op.error_code = "PROVIDER_RATE_LIMITED"
                op.error_summary = error_text
                op.completed_at = datetime.now(UTC)
                await session.commit()
                raise ProviderRateLimitedError(retry_after_seconds=retry_after)
            op.status = "failed"
            op.error_code = "PROVIDER_CREATE_FAILED"
            op.error_summary = error_text
            failure_summary: dict[str, object] = {
                "create_status": result.status,
                "create_error": error_text[:300],
            }
            if result.error_code:
                failure_summary["provider_error_code"] = str(result.error_code)
            if result.http_status is not None:
                failure_summary["create_http_status"] = result.http_status
            if result.retry_after_seconds is not None:
                failure_summary["retry_after_seconds"] = result.retry_after_seconds
            op.response_summary = failure_summary
            op.completed_at = datetime.now(UTC)
            await _commit_terminal_failure(
                session,
                run=run,
                error_code="PROVIDER_CREATE_FAILED",
                error_summary=error_text,
            )
            raise ValidationAppError(f"PROVIDER_CREATE_FAILED: {error_text}")
        remote = str(result.remote_task_id or "")
        synchronous_image = (
            isinstance(compiled, CompiledImageRequest)
            and result.status == "succeeded"
            and (result.artifact_uri is not None or result.artifact_bytes is not None)
        )
        if not remote and not synchronous_image:
            op.status = "failed"
            op.error_code = "PROVIDER_RESPONSE_INVALID"
            op.error_summary = "provider create response has no remote task id"
            op.completed_at = datetime.now(UTC)
            await _commit_terminal_failure(
                session,
                run=run,
                error_code="PROVIDER_RESPONSE_INVALID",
                error_summary=op.error_summary,
            )
            raise ValidationAppError("PROVIDER_RESPONSE_INVALID")
        op.provider_operation_id = remote or None
        op.remote_secondary_id = result.remote_secondary_id
        op.status = "submission_started" if synchronous_image and not remote else "submitted"
        if result.resume_token is not None:
            op.resume_token = result.resume_token.model_dump(mode="json")
            resume = result.resume_token
        op.response_summary = {
            "create_status": result.status,
            "query_kind": result.query_kind,
        }
        # Synchronous image submissions already carry the result URL; no poll.
        op.request_summary = {
            **op.request_summary,
            **result.request_summary,
            "execution_identity": identity_json,
        }
        await session.flush()
        await session.commit()
        await set_node_run_rls_context(session, node_run_id=run.id)

    if runtime is None:
        raise ValidationAppError("unified runtime was not resolved")
    if resume is None and not synchronous_image:
        raise ValidationAppError("unified operation has no resume token")
    if resume is not None:
        require_resume_token_identity(
            resume,
            remote_task_id=op.provider_operation_id,
            provider_type=op.actual_provider,
            protocol_profile=op.protocol_profile,
            remote_secondary_id=op.remote_secondary_id,
        )

    # A submitted task yields immediately. Each later attempt observes it once;
    # synchronous images already carry their output and need no poll job.
    if not synchronous_image:
        assert resume is not None
        _cancel_requested, cancel_confirmed = await _request_remote_cancellation_once(
            session,
            run=run,
            operation=op,
            runtime=runtime,
            resume=resume,
        )
        if cancel_confirmed:
            await _commit_provider_cancelled(
                session,
                run=run,
                operation=op,
                reason="provider_confirmed_cancellation",
            )
            raise ProviderTaskCancelledError()
        poll_interval_s = 5.0 if node_type in {"video", "video_review"} else 3.0
        poll_count = _counter((op.response_summary or {}).get("poll_count", 0))
        if create_status != "resumed":
            await _defer_remote_poll(
                session,
                run=run,
                operation=op,
                delay_seconds=poll_interval_s,
                expected_started_at=attempt_started_at,
            )
        try:
            async with asyncio.timeout(POLL_OBSERVATION_TIMEOUT_SECONDS):
                poll = await runtime.poll_video(resume)
        except TimeoutError:
            # Poll is observation of a known remote ID. A lost observation never
            # authorizes create or reinterprets the frozen execution identity.
            poll = PollResult(status="running", error_code="PROVIDER_POLL_OBSERVATION_TIMEOUT")
        poll_count += 1
        status = str(poll.status)
        op.last_polled_at = datetime.now(UTC)
        if op.status != "cancel_requested":
            op.status = "running"
        summary = {**dict(op.response_summary or {}), "poll_count": poll_count}
        if poll.error_code or (poll.http_status is not None and poll.http_status >= 400):
            summary["last_poll_error"] = str(poll.error_code or f"http_{poll.http_status}")[:200]
            raw_count = summary.get("poll_error_count", 0) or 0
            summary["poll_error_count"] = (raw_count if isinstance(raw_count, int) else 0) + 1
            if poll.http_status is not None:
                summary["last_poll_http_status"] = poll.http_status
        op.response_summary = summary
        # Terminal remote truth wins over a simultaneous cancellation request.
        if status == "cancelled":
            await _commit_provider_cancelled(
                session,
                run=run,
                operation=op,
                reason="provider_confirmed_cancellation",
            )
            raise ProviderTaskCancelledError()
        if status not in {"succeeded", "completed", "success", "failed"}:
            _cancel_requested, cancel_confirmed = await _request_remote_cancellation_once(
                session,
                run=run,
                operation=op,
                runtime=runtime,
                resume=resume,
            )
            if cancel_confirmed:
                await _commit_provider_cancelled(
                    session,
                    run=run,
                    operation=op,
                    reason="provider_confirmed_cancellation",
                )
                raise ProviderTaskCancelledError()
            poll_retry_after = poll.retry_after_seconds
            delay = poll_interval_s
            if poll.error_code:
                errors = _counter(summary.get("poll_error_count", 0))
                delay = min(MAX_POLL_ERROR_BACKOFF_SECONDS, delay * 2 ** min(errors, 6))
            if isinstance(poll_retry_after, int | float) and math.isfinite(poll_retry_after):
                delay = max(delay, float(poll_retry_after))
            await _defer_remote_poll(
                session,
                run=run,
                operation=op,
                delay_seconds=delay,
                expected_started_at=attempt_started_at,
            )
    else:
        assert result is not None and (
            result.artifact_uri is not None or result.artifact_bytes is not None
        )
        poll = PollResult(status="succeeded", artifact_uri=result.artifact_uri)
        poll_count = 0

    cost = (
        await runtime.fetch_cost(resume)
        if resume is not None
        else CostResult(cost_status="not_reported")
    )
    status = str(poll.status)
    cost_amount = getattr(cost, "amount", None)
    cost_status = str(getattr(cost, "cost_status", "not_reported"))
    op.provider_cost = Decimal(str(cost_amount)) if cost_amount is not None else None
    if cost_amount is not None or cost_status in {"reported", "reconciled"}:
        op.currency = str(getattr(cost, "currency", op.currency)).upper()
    prior_response_summary = dict(op.response_summary or {})
    op.response_summary = {
        **prior_response_summary,
        "create_status": create_status,
        "final_status": status,
        "poll_count": poll_count,
        "query_kind": resume.query_kind if resume else None,
        "provider_reported_cost": (str(op.provider_cost) if op.provider_cost is not None else None),
        "cost_status": cost_status,
    }
    if status not in {"succeeded", "completed", "success"}:
        error_summary = str(getattr(poll, "error_code", None) or status)[:500]
        op.status = "failed"
        op.error_code = "PROVIDER_FAILED"
        op.error_summary = error_summary
        op.completed_at = datetime.now(UTC)
        await _commit_terminal_failure(
            session,
            run=run,
            error_code="PROVIDER_FAILED",
            error_summary=error_summary,
        )
        raise ValidationAppError(f"PROVIDER_FAILED: {error_summary}")

    op.status = "succeeded"
    op.error_code = None
    op.error_summary = None
    op.completed_at = datetime.now(UTC)
    uri: object = (
        result.artifact_bytes
        if synchronous_image and result and result.artifact_bytes is not None
        else poll.artifact_uri
    )
    with OwnedMediaDirectory(operation_id=run.id) as scratch:
        destination = Path(scratch) / "result.media"
        if uri == PROVIDER_CONTENT_URI:
            assert resume is not None
            fetch_artifact = getattr(runtime, "fetch_artifact", None)
            if not callable(fetch_artifact):
                raise ValidationAppError("PROVIDER_MEDIA_MISSING: runtime cannot fetch content")
            media = await fetch_artifact(resume, destination=destination)
            with media.path.open("rb") as source:
                _validate_provider_media(
                    kind=node_type, data=source.read(64), content_type=media.content_type
                )
        else:
            media = await _resolve_media_file(
                kind=node_type,
                remote=remote,
                prompt=prompt,
                artifact_uri=uri,
                destination=destination,
            )
        mime, ext, art_type = _mime_for_node(node_type)
        with media.path.open("rb") as source:
            detected = _detected_media_format(kind=node_type, header=source.read(64))
        if detected is not None:
            mime, ext = detected
        object_key = f"projects/{run.project_id}/nodes/{node.node_key}/{run.id}.{ext}"
        media_metadata = _inspect_media_metadata(kind=node_type, path=media.path)
        stored = await obj_store.put_file(object_key=object_key, path=media.path, mime_type=mime)
    art = await get_or_create_artifact(
        session,
        project_id=run.project_id,
        artifact_type=art_type,
        object_key=stored.object_key,
        content_hash=stored.content_hash,
        mime_type=stored.mime_type,
        byte_size=stored.byte_size,
        produced_by_run_id=run.id,
    )
    _apply_media_metadata(art, media_metadata)

    # Serialize the final local state with a concurrent cancellation request.
    # If cancellation committed first, retain the immutable late Artifact but
    # never make it the graph's latest successful/Formal input.
    await session.refresh(run, with_for_update=True)
    if not _same_attempt(run.started_at, attempt_started_at):
        raise NodeRunAlreadyClaimedError()
    completed_after_cancel = _cancellation_requested(run)
    run.status = "completed_after_cancel" if completed_after_cancel else "completed"
    run.error_code = None
    run.error_summary = None
    run.result_artifact_id = art.id
    run.provider_cost = op.provider_cost or Decimal("0")
    run.finished_at = datetime.now(UTC)
    run.output_summary = {
        "artifact_id": str(art.id),
        "node_type": node_type,
        "byte_size": art.byte_size,
        "content_hash": art.content_hash,
        "source_commit": get_settings().source_commit,
        "identity_evidence_policy": identity_evidence_policy_snapshot(),
        "execution_path": UNIFIED_PATH_VERSION,
        "completed_after_cancel": completed_after_cancel,
        "adopted_after_cancel": False if completed_after_cancel else None,
    }
    if not completed_after_cancel:
        node.latest_successful_run_id = run.id
    await session.flush()
    return ExecuteNodeResult(
        node_run_id=run.id,
        artifact_id=art.id,
        object_key=art.object_key,
        content_hash=art.content_hash,
        byte_size=art.byte_size,
        identity_status=None,
        provider_operation_id=op.id,
        node_type=node_type,
    )
