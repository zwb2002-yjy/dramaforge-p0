"""Local voice concatenation for segmented speech (I8a-03).

The concat node depends on the segment voice nodes through required GraphEdges.
It never calls a Provider: it reads the completed segment WAV artifacts from the
object store, joins their PCM frames and stores one artifact. A missing or
incomplete segment defers the run instead of inventing audio.
"""

from __future__ import annotations

import io
import wave
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.execution.artifact_lineage import get_or_create_artifact
from app.execution.models import Artifact, GraphEdge, GraphNode, NodeRun
from app.shared.errors import ProviderTaskPendingError, ValidationAppError
from app.storage.minio_store import ObjectStore


async def _segment_artifacts(
    session: AsyncSession, *, run: NodeRun, node: GraphNode
) -> list[Artifact]:
    upstream_nodes = (
        await session.execute(
            select(GraphNode)
            .select_from(GraphEdge)
            .join(GraphNode, GraphNode.id == GraphEdge.upstream_node_id)
            .where(GraphEdge.graph_version_id == run.graph_version_id)
            .where(GraphEdge.downstream_node_id == node.id)
            .where(GraphEdge.required.is_(True))
            .order_by(GraphNode.node_key)
        )
    ).scalars().all()
    if not upstream_nodes:
        raise ValidationAppError(
            "voice_concat has no required segment edges",
            details={"code": "VOICE_CONCAT_INPUTS_MISSING"},
        )
    artifacts: list[Artifact] = []
    for upstream in upstream_nodes:
        segment_run = await session.scalar(
            select(NodeRun)
            .where(NodeRun.graph_node_id == upstream.id)
            .where(NodeRun.status.in_(["completed", "cached", "completed_after_cancel"]))
            .order_by(NodeRun.attempt_no.desc())
            .limit(1)
        )
        if segment_run is None or segment_run.result_artifact_id is None:
            raise ProviderTaskPendingError()
        artifact = await session.get(Artifact, segment_run.result_artifact_id)
        if artifact is None:
            raise ValidationAppError(
                "voice_concat segment artifact is missing",
                details={"code": "VOICE_CONCAT_INPUTS_MISSING"},
            )
        artifacts.append(artifact)
    return artifacts


def _concat_wav(parts: list[bytes]) -> bytes:
    frames: list[bytes] = []
    params: tuple[int, int, int] | None = None
    for part in parts:
        with wave.open(io.BytesIO(part), "rb") as wav:
            current = (wav.getnchannels(), wav.getsampwidth(), wav.getframerate())
            if params is None:
                params = current
            elif current != params:
                raise ValidationAppError(
                    "voice segments use different audio formats",
                    details={"code": "VOICE_CONCAT_FORMAT_MISMATCH"},
                )
            frames.append(wav.readframes(wav.getnframes()))
    if params is None:
        raise ValidationAppError(
            "voice_concat has no audio", details={"code": "VOICE_CONCAT_INPUTS_MISSING"}
        )
    target = io.BytesIO()
    with wave.open(target, "wb") as out:
        out.setnchannels(params[0])
        out.setsampwidth(params[1])
        out.setframerate(params[2])
        for frame in frames:
            out.writeframes(frame)
    return target.getvalue()


async def execute_voice_concat_node_run(
    session: AsyncSession,
    *,
    run: NodeRun,
    node: GraphNode,
    store: ObjectStore,
) -> None:
    artifacts = await _segment_artifacts(session, run=run, node=node)
    parts: list[bytes] = []
    for artifact in artifacts:
        if artifact.storage_state != "available" or artifact.deleted_at is not None:
            raise ValidationAppError(
                "voice_concat segment artifact is unavailable",
                details={"code": "VOICE_CONCAT_INPUTS_MISSING"},
            )
        try:
            parts.append(await store.get_bytes(object_key=artifact.object_key))
        except Exception as exc:  # noqa: BLE001 - storage read must fail closed
            raise ValidationAppError(
                "voice_concat segment bytes are unavailable",
                details={"code": "VOICE_CONCAT_INPUTS_MISSING"},
            ) from exc
    data = _concat_wav(parts)
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
    )
    run.status = "completed"
    run.result_artifact_id = artifact.id
    run.provider_cost = Decimal("0")
    run.platform_cost = Decimal("0")
    run.finished_at = datetime.now(UTC)
    run.output_summary = {
        "artifact_id": str(artifact.id),
        "node_type": "voice_concat",
        "byte_size": artifact.byte_size,
        "content_hash": artifact.content_hash,
        "segment_count": len(parts),
    }

__all__ = ["execute_voice_concat_node_run"]
