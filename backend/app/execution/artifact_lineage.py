"""Artifact identity and NodeRun lineage invariants."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.execution.models import Artifact, NodeRun
from app.shared.errors import ValidationAppError


async def get_or_create_artifact(
    session: AsyncSession,
    *,
    project_id: UUID,
    artifact_type: str,
    object_key: str,
    content_hash: str,
    mime_type: str,
    byte_size: int,
    produced_by_run_id: UUID | None,
    allow_cross_run_reuse: bool = False,
) -> Artifact:
    """Persist an Artifact without reassigning Shot media between NodeRuns."""
    existing = (
        await session.execute(
            select(Artifact).where(
                Artifact.project_id == project_id,
                Artifact.content_hash == content_hash,
                Artifact.artifact_type == artifact_type,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if (
            artifact_type != "document"
            and produced_by_run_id is not None
            and existing.produced_by_run_id is not None
            and existing.produced_by_run_id != produced_by_run_id
        ):
            current_run = await session.get(NodeRun, produced_by_run_id)
            source_run = await session.get(NodeRun, existing.produced_by_run_id)
            current_shot_id = str(
                (current_run.input_snapshot or {}).get("shot_id") if current_run else ""
            )
            source_shot_id = str(
                (source_run.input_snapshot or {}).get("shot_id") if source_run else ""
            )
            if current_shot_id and not allow_cross_run_reuse:
                raise ValidationAppError(
                    "ARTIFACT_NOT_INDEPENDENT: Shot NodeRun produced bytes already "
                    "claimed by a different NodeRun",
                    details={
                        "code": "ARTIFACT_NOT_INDEPENDENT",
                        "current_run_id": str(produced_by_run_id),
                        "source_run_id": str(existing.produced_by_run_id),
                        "current_shot_id": current_shot_id,
                        "source_shot_id": source_shot_id,
                        "artifact_id": str(existing.id),
                    },
                )
        if existing.storage_state != "available":
            existing.storage_state = "available"
        if produced_by_run_id and existing.produced_by_run_id is None:
            existing.produced_by_run_id = produced_by_run_id
        await session.flush()
        return existing

    artifact = Artifact(
        project_id=project_id,
        artifact_type=artifact_type,
        storage_state="available",
        object_key=object_key,
        content_hash=content_hash,
        mime_type=mime_type,
        byte_size=byte_size,
        produced_by_run_id=produced_by_run_id,
    )
    session.add(artifact)
    await session.flush()
    return artifact
