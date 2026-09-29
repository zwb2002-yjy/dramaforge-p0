"""Record exact-revision model visibility without trusting legacy probe flags."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.providers.model_system_models import (
    ProviderAvailabilityEvidence,
    ProviderModelAvailability,
)
from app.providers.models import ProviderConnection, ProviderConnectionRevision

AvailabilityStatus = Literal[
    "visible",
    "not_visible",
    "auth_failed",
    "forbidden",
    "region_unavailable",
    "temporary_error",
    "not_supported",
]


@dataclass(frozen=True)
class ModelAvailabilityObservation:
    workspace_id: UUID
    connection_id: UUID
    connection_revision_id: UUID
    credential_revision_id: UUID
    remote_model_id: str
    verifier_kind: str
    status: AvailabilityStatus
    listed_model_ids: tuple[str, ...] | None = None
    error_code: str | None = None

    def validate(self) -> None:
        if not self.remote_model_id.strip():
            raise ValueError("remote model id is required")
        if self.status in {"visible", "not_visible"}:
            if self.listed_model_ids is None:
                raise ValueError("model-list visibility requires the returned model ids")
            listed = set(self.listed_model_ids)
            if (self.remote_model_id in listed) != (self.status == "visible"):
                raise ValueError("availability status contradicts the returned model ids")
        elif self.listed_model_ids is not None:
            raise ValueError("failed checks cannot claim a model-list result")


def effective_availability(
    previous: str | None, observation: AvailabilityStatus
) -> str:
    """Only a positive check creates visible; transient failure preserves state."""
    if observation == "temporary_error":
        return previous or "not_checked"
    return observation


async def record_model_availability(
    session: AsyncSession, observation: ModelAvailabilityObservation
) -> ProviderModelAvailability:
    """Append evidence and update the projection under a connection row lock.

    The lock serializes concurrent first observations, where no projection row
    exists yet. A stale revision can retain its own evidence but cannot confer
    visibility on a newer revision because the key includes both revision IDs.
    """
    observation.validate()
    connection = await session.scalar(
        select(ProviderConnection)
        .where(
            ProviderConnection.id == observation.connection_id,
            ProviderConnection.workspace_id == observation.workspace_id,
        )
        .with_for_update()
    )
    if connection is None:
        raise ValueError("provider connection does not belong to the workspace")
    revision = await session.scalar(
        select(ProviderConnectionRevision).where(
            ProviderConnectionRevision.id == observation.connection_revision_id,
            ProviderConnectionRevision.connection_id == connection.id,
        )
    )
    if revision is None or revision.credential_revision_id != observation.credential_revision_id:
        raise ValueError("availability observation has an invalid connection revision")

    evidence = ProviderAvailabilityEvidence(
        workspace_id=observation.workspace_id,
        connection_id=connection.id,
        connection_revision_id=revision.id,
        credential_revision_id=revision.credential_revision_id,
        remote_model_id=observation.remote_model_id,
        verifier_kind=observation.verifier_kind,
        status=observation.status,
        listed_model_ids_json=(
            list(observation.listed_model_ids) if observation.listed_model_ids is not None else None
        ),
        error_code=observation.error_code,
    )
    session.add(evidence)
    await session.flush()
    projection = await session.scalar(
        select(ProviderModelAvailability)
        .where(
            ProviderModelAvailability.connection_revision_id == revision.id,
            ProviderModelAvailability.credential_revision_id == revision.credential_revision_id,
            ProviderModelAvailability.remote_model_id == observation.remote_model_id,
        )
        .with_for_update()
    )
    if projection is None:
        projection = ProviderModelAvailability(
            workspace_id=observation.workspace_id,
            connection_id=connection.id,
            connection_revision_id=revision.id,
            credential_revision_id=revision.credential_revision_id,
            remote_model_id=observation.remote_model_id,
            effective_status=effective_availability(None, observation.status),
            positive_evidence_id=(evidence.id if observation.status == "visible" else None),
            latest_evidence_id=evidence.id,
        )
        session.add(projection)
    else:
        projection.effective_status = effective_availability(
            projection.effective_status, observation.status
        )
        if observation.status == "visible":
            projection.positive_evidence_id = evidence.id
        projection.latest_evidence_id = evidence.id
        projection.updated_at = datetime.now(UTC)
    await session.flush()
    return projection
