"""Canonical speech execution with immutable engine/voice identity and WAV artifacts.

Network Edge speech is explicit and best-effort; local legacy speech is never
a fallback. Both use the existing NodeRun → ProviderOperation → Artifact chain.
"""

from __future__ import annotations

import hashlib
import io
import json
import wave
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.voice import VoiceExecutionSpec
from app.execution.artifact_lineage import get_or_create_artifact
from app.execution.models import GraphNode, NodeRun, ProviderOperation
from app.providers.voice_config import voice_identity
from app.providers.voice_runtime import get_voice_adapter
from app.shared.db import set_node_run_rls_context
from app.shared.errors import ValidationAppError
from app.storage.minio_store import ObjectStore

if TYPE_CHECKING:
    from app.execution.run_state import ExecuteNodeResult


async def execute_voice_node_run(
    session: AsyncSession,
    *,
    run: NodeRun,
    node: GraphNode,
    snapshot: dict[str, object],
    store: ObjectStore,
    prompt: str,
) -> ExecuteNodeResult:
    """Execute the speech identity frozen by the explicit Export/production gate."""

    from app.execution.run_state import ExecuteNodeResult, _commit_terminal_failure

    raw_spec = snapshot.get("voice_execution")
    if not isinstance(raw_spec, dict):
        raise ValidationAppError(
            "VOICE_IDENTITY_MISSING: 请重新确认导出，旧任务缺少冻结的配音身份。"
        )
    spec = VoiceExecutionSpec.model_validate(raw_spec)
    provider, model, path_version = voice_identity(spec)
    adapter = get_voice_adapter(spec)
    operation = await session.scalar(
        select(ProviderOperation)
        .where(ProviderOperation.node_run_id == run.id)
        .order_by(ProviderOperation.attempt_no.desc(), ProviderOperation.created_at.desc())
        .limit(1)
    )
    request_fingerprint = hashlib.sha256(
        json.dumps(
            {"text": prompt, "input_hash": run.input_hash, "voice": spec.model_dump()},
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    if operation is not None and (
        operation.request_fingerprint != request_fingerprint
        or operation.actual_provider != provider
        or operation.actual_model != model
        or operation.execution_path_version != path_version
    ):
        raise ValidationAppError(
            "VOICE_IDENTITY_MISMATCH: 已有配音请求与冻结身份不一致，拒绝重试。"
        )
    if operation is None:
        operation = ProviderOperation(
            node_run_id=run.id,
            attempt_no=run.attempt_no,
            purpose="primary",
            operation_kind="voice.generate",
            actual_provider=provider,
            actual_model=model,
            request_fingerprint=request_fingerprint,
            status="submission_started",
            request_summary={
                "kind": "voice",
                "execution_path": path_version,
                "voice_execution": spec.model_dump(mode="json"),
            },
            response_summary={},
            submitted_at=datetime.now(UTC),
            provider_cost=Decimal("0"),
            currency="USD",
            execution_path_version=path_version,
        )
        session.add(operation)
    await session.flush()
    await session.commit()
    # The worker establishes the node-run scope with SET LOCAL.  That scope is
    # cleared by the operation commit, so restore it before inserting the WAV
    # Artifact and updating the operation/run lineage.
    if await set_node_run_rls_context(session, node_run_id=run.id) is None:
        raise ValidationAppError("voice node ownership context unavailable")

    created = await adapter.create({"prompt": prompt, "kind": "voice"})
    remote = str(created.get("remote_task_id") or "")
    if str(created.get("status") or "failed") not in {"succeeded", "completed", "success"}:
        message = str(created.get("error") or "voice runtime failed")[:500]
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
        message = str(polled.get("error") or "voice runtime failed")[:500]
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
        message = "voice runtime returned no WAV bytes"
        operation.status = "failed"
        operation.error_code = "VOICE_OUTPUT_MISSING"
        operation.error_summary = message
        operation.completed_at = datetime.now(UTC)
        await _commit_terminal_failure(
            session, run=run, error_code="VOICE_OUTPUT_MISSING", error_summary=message
        )
        raise ValidationAppError(f"VOICE_OUTPUT_MISSING: {message}")

    try:
        with wave.open(io.BytesIO(data), "rb") as audio:
            samples = audio.readframes(audio.getnframes())
            duration = Decimal(len(samples)) / Decimal(
                audio.getframerate() * audio.getnchannels() * audio.getsampwidth()
            )
            if duration <= 0 or audio.getcomptype() != "NONE":
                raise ValueError("empty or unsupported WAV")
    except (wave.Error, EOFError, ValueError, ZeroDivisionError) as exc:
        operation.status = "failed"
        operation.error_code = "VOICE_OUTPUT_INVALID"
        operation.error_summary = "配音返回的文件不是有效的非空 PCM WAV。"
        operation.completed_at = datetime.now(UTC)
        await _commit_terminal_failure(
            session,
            run=run,
            error_code="VOICE_OUTPUT_INVALID",
            error_summary=operation.error_summary,
        )
        raise ValidationAppError("VOICE_OUTPUT_INVALID") from exc

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
    if artifact.duration_seconds is None:
        artifact.duration_seconds = duration
    operation.provider_operation_id = remote
    operation.status = "succeeded"
    operation.provider_cost = Decimal("0")
    operation.response_summary = {
        "status": "succeeded",
        "local": spec.engine != "edge-tts",
        "voice_execution": spec.model_dump(mode="json"),
    }
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
        "source": provider,
        "voice_execution": spec.model_dump(mode="json"),
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
