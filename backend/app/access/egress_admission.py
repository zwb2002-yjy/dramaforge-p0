"""Single egress admission decision for every real outbound path.

One call answers: may this project send this payload, for these purposes, to this
destination, right now? It reads the current policy head (never a cache), the
declared destination revision and — when inputs are supplied — the source-use
declarations. The result is frozen into the invocation/operation evidence before
the network call, so a later policy change cannot rewrite what was admitted.

The historical ``current`` mode keeps behaving as before; new autonomous or
strict paths must name a trusted destination and cover every required purpose.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.egress_models import (
    EGRESS_PURPOSES,
    ProjectEgressPolicyHead,
    ProjectEgressPolicyRevision,
    ProviderDestinationRevision,
)
from app.access.models import Project
from app.shared.errors import ValidationAppError


@dataclass(frozen=True)
class AdmissionDecision:
    allowed: bool
    mode: str
    purpose: str
    required_purposes: tuple[str, ...]
    policy_revision_id: UUID | None
    policy_revision: int
    destination_revision_id: UUID | None
    processing_location: str | None
    reason_code: str
    source_use: dict[str, object] = field(default_factory=dict)

    def evidence(self) -> dict[str, object]:
        """The frozen admission block stored with the original call."""
        return {
            "schema_version": 1,
            "decision": "allowed" if self.allowed else "refused",
            "mode": self.mode,
            "purpose": self.purpose,
            "required_purposes": list(self.required_purposes),
            "policy_revision_id": str(self.policy_revision_id) if self.policy_revision_id else None,
            "policy_revision": self.policy_revision,
            "destination_revision_id": (
                str(self.destination_revision_id) if self.destination_revision_id else None
            ),
            "processing_location": self.processing_location,
            "reason_code": self.reason_code,
            "source_use": dict(self.source_use),
        }


class EgressAdmission:
    """Read-only admission; callers freeze the decision before sending."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _policy(
        self, project: Project,
    ) -> tuple[ProjectEgressPolicyRevision | None, int]:
        head = await self._session.scalar(
            select(ProjectEgressPolicyHead).execution_options(populate_existing=True).where(
                ProjectEgressPolicyHead.project_id == project.id
            )
        )
        if head is None:
            return None, 0
        revision = await self._session.scalar(
            select(ProjectEgressPolicyRevision).where(
                ProjectEgressPolicyRevision.id == head.current_revision_id,
                ProjectEgressPolicyRevision.project_id == project.id,
            )
        )
        return revision, head.revision

    async def _destination(
        self, project: Project, destination_id: UUID | None,
    ) -> ProviderDestinationRevision | None:
        if destination_id is None:
            return None
        return cast(
            ProviderDestinationRevision | None,
            await self._session.scalar(
                select(ProviderDestinationRevision).where(
                    ProviderDestinationRevision.id == destination_id,
                    ProviderDestinationRevision.workspace_id == project.workspace_id,
                )
            ),
        )

    async def decide(
        self,
        project: Project,
        *,
        purpose: str,
        required_purposes: list[str] | None = None,
        destination_id: UUID | None = None,
        processing_location: str | None = None,
        source_use: dict[str, object] | None = None,
    ) -> AdmissionDecision:
        required = tuple(sorted({str(value) for value in (required_purposes or [purpose])}))
        if purpose not in EGRESS_PURPOSES or any(p not in EGRESS_PURPOSES for p in required):
            raise ValidationAppError(
                "未知的外发用途", details={"code": "EGRESS_PURPOSE_INVALID"},
            )
        if purpose not in required:
            raise ValidationAppError(
                "required_purposes 必须包含主用途", details={"code": "EGRESS_PURPOSE_INVALID"},
            )
        revision, head_revision = await self._policy(project)
        mode = revision.mode if revision is not None else "current"
        policy_id = revision.id if revision is not None else None
        source_decision = dict(source_use or {})

        def decision(
            allowed: bool, reason: str, *,
            destination: ProviderDestinationRevision | None = None,
            location: str | None = None,
        ) -> AdmissionDecision:
            return AdmissionDecision(
                allowed=allowed,
                mode=mode,
                purpose=purpose,
                required_purposes=required,
                policy_revision_id=policy_id,
                policy_revision=head_revision,
                destination_revision_id=(
                    destination.id if destination is not None else destination_id
                ),
                processing_location=location,
                reason_code=reason,
                source_use=source_decision,
            )

        # The source declaration gate is independent of destination policy.
        if source_decision and not source_decision.get("allowed", True):
            return decision(False, "SOURCE_USE_BLOCKED", location=processing_location)
        if mode == "current":
            return decision(True, "legacy_current", location=processing_location)
        destination = await self._destination(project, destination_id)
        if mode == "local_only":
            # The caller's observed hop wins; a declared remote destination can
            # never be relabelled local by passing a local hint.
            actual = processing_location
            if destination is not None and (
                destination.processing_location != "local" or actual is None
            ):
                actual = destination.processing_location
            if actual != "local":
                return decision(
                    False, "EGRESS_LOCAL_ONLY", destination=destination, location=actual,
                )
            return decision(True, "local_only_allowed", destination=destination, location=actual)
        # allowlisted
        if destination is None:
            return decision(False, "EGRESS_DESTINATION_REQUIRED", location=processing_location)
        data = revision.policy_data if revision is not None else {}
        raw_ids = data.get("allowed_destination_revision_ids")
        raw_purposes = data.get("allowed_purposes")
        allowed_ids = {str(value) for value in raw_ids} if isinstance(raw_ids, list) else set()
        allowed_purposes = (
            {str(value) for value in raw_purposes} if isinstance(raw_purposes, list) else set()
        )
        if str(destination.id) not in allowed_ids:
            return decision(
                False, "EGRESS_DESTINATION_NOT_ALLOWED",
                destination=destination, location=destination.processing_location,
            )
        if not set(required) <= allowed_purposes:
            return decision(
                False, "EGRESS_PURPOSE_NOT_ALLOWED",
                destination=destination, location=destination.processing_location,
            )
        declared = {str(value) for value in destination.purposes}
        if not set(required) <= declared:
            return decision(
                False, "EGRESS_DESTINATION_PURPOSE_MISSING",
                destination=destination, location=destination.processing_location,
            )
        if destination.processing_location == "unknown" and processing_location != "unknown":
            return decision(
                False, "EGRESS_LOCATION_UNVERIFIED",
                destination=destination, location=destination.processing_location,
            )
        return decision(
            True, "allowlisted_allowed",
            destination=destination, location=destination.processing_location,
        )


__all__ = ["AdmissionDecision", "EgressAdmission"]
