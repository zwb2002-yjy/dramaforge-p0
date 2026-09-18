"""Binding-driven Provider submission, recovery, cancellation and result persistence."""

from __future__ import annotations

import asyncio
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project
from app.config import get_settings
from app.consistency.identity_policy import (
    identity_evidence_policy_snapshot,
)
from app.execution.artifact_lineage import get_or_create_artifact
from app.execution.media_io import (
    _apply_media_metadata,
    _inspect_media_metadata,
    _mime_for_node,
    _resolve_media_bytes,
)
from app.execution.media_submission import prepare_media_submission
from app.execution.models import Artifact, GraphNode, NodeRun, ProviderOperation
from app.execution.run_state import (
    UNIFIED_PATH_VERSION,
    ExecuteNodeResult,
    _commit_terminal_failure,
)
from app.shared.db import set_node_run_rls_context
from app.shared.errors import (
    ProviderTaskCancelledError,
    ProviderTaskPendingError,
    ValidationAppError,
)
from app.storage.minio_store import ObjectStore


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
    from typing import Any

    from app.production.execution_plan import WorkbenchExecutionPlan
    from app.providers.execution_identity import (
        ExecutionIdentitySnapshot,
    )
    from app.providers.models import (
        ProviderConnection,
    )
    from app.providers.registry import get_plugin
    from app.providers.runtime import (
        CompiledImageRequest,
        PollResult,
        ProviderResumeToken,
        ProviderRuntime,
        ProviderRuntimeResolver,
        SubmissionResult,
    )
    from app.providers.workspace_credentials import runtime_connection_settings
    from app.shared.errors import ProviderRateLimitedError

    now = datetime.now(UTC)
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
    connection: Any = None
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
    initial_status = "queued"
    synchronous_image = False
    result: SubmissionResult | None = None

    resubmit = bool(op is not None and op.status == "rejected" and not op.provider_operation_id)
    if op is not None and not resubmit:
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
        # Resume only. Never create a second remote task. Rebuild the runtime
        # exclusively from the persisted execution identity.
        if frozen_identity is not None:
            runtime = await ProviderRuntimeResolver(session).resume_runtime_for_identity(
                identity=frozen_identity,
                workspace_id=project.workspace_id,
                operation=op,
            )
        else:
            connection = (
                await session.get(ProviderConnection, op.connection_id)
                if op.connection_id is not None
                else None
            )
            if connection is None:
                raise ValidationAppError("unified operation connection is missing")
            plugin = get_plugin(connection.provider_type, connection.protocol_profile)
            cfg = await runtime_connection_settings(session, connection=connection)
            runtime = await ProviderRuntimeResolver(session).resume_runtime(
                plugin=plugin, connection=connection, settings=cfg
            )
        if op.resume_token is not None:
            resume = ProviderResumeToken.model_validate(op.resume_token)
        remote = str(op.provider_operation_id or "")
        create_status = "resumed"
        initial_status = "running"

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
        if not remote:
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
        op.provider_operation_id = remote
        op.remote_secondary_id = result.remote_secondary_id
        op.status = "submitted"
        if result.resume_token is not None:
            op.resume_token = result.resume_token.model_dump(mode="json")
            resume = result.resume_token
        op.response_summary = {
            "create_status": result.status,
            "query_kind": result.query_kind,
        }
        # Synchronous image submissions already carry the result URL; no poll.
        synchronous_image = (
            isinstance(compiled, CompiledImageRequest)
            and result.status == "succeeded"
            and result.artifact_uri is not None
        )
        op.request_summary = {
            **op.request_summary,
            **result.request_summary,
            "execution_identity": identity_json,
        }
        initial_status = str(result.status)
        await session.flush()
        await session.commit()
        await set_node_run_rls_context(session, node_run_id=run.id)

    if runtime is None:
        raise ValidationAppError("unified runtime was not resolved")
    if resume is None:
        raise ValidationAppError("unified operation has no resume token")

    # Poll loop (resume token driven). Synchronous image submissions already
    # carry the result URL and skip polling entirely.
    if not synchronous_image:
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
        poll_timeout_s = 1_620.0 if node_type in {"video", "video_review"} else 120.0
        poll_interval_s = 5.0 if node_type in {"video", "video_review"} else 3.0
        deadline = asyncio.get_running_loop().time() + poll_timeout_s
        poll = PollResult(status=initial_status)
        poll_count = 0
        while True:
            poll = await runtime.poll_video(resume)
            poll_count += 1
            status = str(poll.status)
            op.last_polled_at = datetime.now(UTC)
            if op.status != "cancel_requested":
                op.status = "running"
            poll_error = poll.error_code
            if poll.http_status is not None or poll_error:
                summary = dict(op.response_summary or {})
                summary["last_poll_error"] = str(poll_error or f"http_{poll.http_status}")[:200]
                raw_count = summary.get("poll_error_count", 0) or 0
                summary["poll_error_count"] = (raw_count if isinstance(raw_count, int) else 0) + 1
                if poll.http_status is not None:
                    summary["last_poll_http_status"] = poll.http_status
                op.response_summary = summary
                await session.commit()
                await set_node_run_rls_context(session, node_run_id=run.id)
            cancel_confirmed = False
            # Terminal poll truth wins. In particular a late success must be
            # imported as completed_after_cancel, not overwritten by a cancel ack.
            if status not in {"succeeded", "completed", "success", "failed", "cancelled"}:
                _cancel_requested, cancel_confirmed = await _request_remote_cancellation_once(
                    session,
                    run=run,
                    operation=op,
                    runtime=runtime,
                    resume=resume,
                )
            if cancel_confirmed or status == "cancelled":
                await _commit_provider_cancelled(
                    session,
                    run=run,
                    operation=op,
                    reason="provider_confirmed_cancellation",
                )
                raise ProviderTaskCancelledError()
            if status in {"succeeded", "completed", "success", "failed"}:
                break
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                op.status = "timed_out"
                op.error_code = "PROVIDER_POLL_TIMEOUT"
                op.error_summary = (
                    f"remote task still pending after {poll_timeout_s:.0f}s; resume polling"
                )
                op.response_summary = {
                    **dict(op.response_summary or {}),
                    "create_status": create_status,
                    "final_status": "running",
                    "poll_count": poll_count,
                    "query_kind": resume.query_kind,
                }
                run.status = "queued"
                run.error_code = "PROVIDER_TASK_PENDING"
                run.error_summary = "Remote Provider task is still running"
                run.output_summary = {
                    "status": "provider_pending",
                    "provider_operation_id": str(op.id),
                }
                await session.commit()
                raise ProviderTaskPendingError()
            poll_retry_after = poll.retry_after_seconds
            sleep_s = poll_interval_s
            if isinstance(poll_retry_after, int | float) and poll_retry_after > 0:
                sleep_s = max(sleep_s, float(poll_retry_after))
            await asyncio.sleep(min(sleep_s, remaining))
    else:
        assert result is not None and result.artifact_uri is not None
        poll = PollResult(status="succeeded", artifact_uri=result.artifact_uri)
        poll_count = 0

    cost = await runtime.fetch_cost(resume)
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
        "query_kind": resume.query_kind,
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
    op.completed_at = datetime.now(UTC)
    uri = poll.artifact_uri
    data = await _resolve_media_bytes(
        kind=node_type,
        remote=remote,
        prompt=prompt,
        artifact_uri=uri,
    )

    mime, ext, art_type = _mime_for_node(node_type)
    object_key = f"projects/{run.project_id}/nodes/{node.node_key}/{run.id}.{ext}"
    media_metadata = _inspect_media_metadata(kind=node_type, data=data)
    stored = await obj_store.put_bytes(object_key=object_key, data=data, mime_type=mime)
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
    completed_after_cancel = _cancellation_requested(run)
    run.status = "completed_after_cancel" if completed_after_cancel else "completed"
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
