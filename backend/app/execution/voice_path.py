"""Canonical local voice-node execution.

Voice is a local, zero-cost runtime capability; it is intentionally separate
from the remote image/video ProviderRuntime contract. It still persists the
same NodeRun → ProviderOperation → Artifact lineage as every other node.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.execution.artifact_lineage import get_or_create_artifact
from app.execution.models import GraphNode, NodeRun, ProviderOperation
from app.providers.voice_runtime import get_voice_adapter
from app.shared.errors import ValidationAppError
from app.storage.minio_store import ObjectStore

if TYPE_CHECKING:
    from app.execution.product_path import ExecuteNodeResult


async def execute_voice_node_run(
    session: AsyncSession,
    *,
    run: NodeRun,
    node: GraphNode,
    snapshot: dict[str, object],
    store: ObjectStore,
    prompt: str,
) -> ExecuteNodeResult:
    """Execute one explicit local TTS node and persist its immutable output."""

    from app.execution.product_path import ExecuteNodeResult, _commit_terminal_failure

    adapter = get_voice_adapter()
    operation = await session.scalar(
        select(ProviderOperation)
        .where(ProviderOperation.node_run_id == run.id)
        .order_by(ProviderOperation.attempt_no.desc(), ProviderOperation.created_at.desc())
        .limit(1)
    )
    request_fingerprint = hashlib.sha256(
        f"voice:{prompt}:{run.input_hash}".encode()
    ).hexdigest()
    if operation is None:
        operation = ProviderOperation(
            node_run_id=run.id,
            attempt_no=run.attempt_no,
            purpose="primary",
            operation_kind="voice.generate",
            actual_provider="local_tts",
            actual_model="espeak-ng",
            request_fingerprint=request_fingerprint,
            status="submission_started",
            request_summary={"kind": "voice", "execution_path": "local-voice-v1"},
            response_summary={},
            submitted_at=datetime.now(UTC),
            provider_cost=Decimal("0"),
            currency="USD",
            execution_path_version="local-voice-v1",
        )
        session.add(operation)
    await session.flush()
    await session.commit()

    created = await adapter.create({"prompt": prompt, "kind": "voice"})
    remote = str(created.get("remote_task_id") or "")
    if str(created.get("status") or "failed") not in {"succeeded", "completed", "success"}:
        message = str(created.get("error") or "local voice runtime failed")[:500]
        operation.status = "failed"
        operation.error_code = "VOICE_RUNTIME_FAILED"
        operation.error_summary = message
        operation.completed_at = datetime.now(UTC)
        await _commit_terminal_failure(
            session, run=run, error_code="VOICE_RUNTIME_FAILED", error_summary=message
        )
        raise ValidationAppError(f"VOICE_RUNTIME_FAILED: {message}")

    polled = await adapter.poll(remote)
    if str(polled.get("status") or "failed") not in {"succeeded", "completed", "success"}:
        message = str(polled.get("error") or "local voice runtime failed")[:500]
        operation.status = "failed"
        operation.error_code = "VOICE_RUNTIME_FAILED"
        operation.error_summary = message
        operation.completed_at = datetime.now(UTC)
        await _commit_terminal_failure(
            session, run=run, error_code="VOICE_RUNTIME_FAILED", error_summary=message
        )
        raise ValidationAppError(f"VOICE_RUNTIME_FAILED: {message}")

    data = adapter.blobs.get(remote)
    if not data:
        message = "local voice runtime returned no WAV bytes"
        operation.status = "failed"
        operation.error_code = "VOICE_OUTPUT_MISSING"
        operation.error_summary = message
        operation.completed_at = datetime.now(UTC)
        await _commit_terminal_failure(
            session, run=run, error_code="VOICE_OUTPUT_MISSING", error_summary=message
        )
        raise ValidationAppError(f"VOICE_OUTPUT_MISSING: {message}")

    stored = await store.put_bytes(
        object_key=f"projects/{run.project_id}/nodes/{node.node_key}/{run.id}.wav",
        data=data,
        mime_type="audio/wav",
    )
    artifact = await get_or_create_artifact(
        session,
        project_id=run.project_id,
        artifact_type="audio",
        object_key=stored.object_key,
        content_hash=stored.content_hash,
        mime_type=stored.mime_type,
        byte_size=stored.byte_size,
        produced_by_run_id=run.id,
        allow_cross_run_reuse=True,
    )
    operation.provider_operation_id = remote
    operation.status = "succeeded"
    operation.provider_cost = Decimal("0")
    operation.response_summary = {"status": "succeeded", "local": True}
    operation.completed_at = datetime.now(UTC)
    run.status = "cached" if artifact.produced_by_run_id != run.id else "completed"
    run.result_artifact_id = artifact.id
    run.reused_from_run_id = (
        artifact.produced_by_run_id if artifact.produced_by_run_id != run.id else None
    )
    run.provider_cost = Decimal("0")
    run.finished_at = datetime.now(UTC)
    run.output_summary = {
        "status": "completed",
        "artifact_id": str(artifact.id),
        "node_type": "voice",
        "content_hash": artifact.content_hash,
        "source": "local_tts",
    }
    node.latest_successful_run_id = run.id
    await session.flush()
    return ExecuteNodeResult(
        node_run_id=run.id,
        artifact_id=artifact.id,
        object_key=artifact.object_key,
        content_hash=artifact.content_hash,
        byte_size=artifact.byte_size,
        identity_status=None,
        provider_operation_id=operation.id,
        node_type="voice",
    )
