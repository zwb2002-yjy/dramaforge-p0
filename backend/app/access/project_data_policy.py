"""Project egress policy: immutable revisions, a mutable head, explicit defaults.

No head means revision 0 in ``current`` mode — the historical behaviour — and a
read never writes. The first write (or the first admission elsewhere) creates the
requested revision directly instead of initialising ``current`` and failing the
caller's own CAS. Only ``allowlisted`` carries destination/permission content, and
every listed destination must belong to the project's workspace and declare every
allowed purpose.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.egress_models import (
    EGRESS_MODES,
    EGRESS_PURPOSES,
    ProjectEgressPolicyHead,
    ProjectEgressPolicyRevision,
    ProviderDestinationRevision,
)
from app.access.models import Project, User
from app.shared.errors import ConflictError, ValidationAppError

_MAX_ITEMS = 100


def _canonical(value: object) -> str:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False,
    )


def policy_hash(
    *, mode: str, destination_ids: list[str], purposes: list[str],
) -> str:
    return hashlib.sha256(
        _canonical(
            {
                "mode": mode,
                "allowed_destination_revision_ids": sorted(destination_ids),
                "allowed_purposes": sorted(purposes),
            }
        ).encode()
    ).hexdigest()


class ProjectDataPolicy:
    """Reads and writes one project's egress permission set."""

    def __init__(self, session: AsyncSession, *, actor: User, project: Project) -> None:
        self._session = session
        self._actor = actor
        self._project = project

    async def head(self) -> ProjectEgressPolicyHead | None:
        return cast(
            ProjectEgressPolicyHead | None,
            await self._session.scalar(
                select(ProjectEgressPolicyHead).where(
                    ProjectEgressPolicyHead.project_id == self._project.id
                )
            ),
        )

    async def current(self) -> ProjectEgressPolicyRevision | None:
        head = await self.head()
        if head is None:
            return None
        return cast(
            ProjectEgressPolicyRevision | None,
            await self._session.scalar(
                select(ProjectEgressPolicyRevision).where(
                    ProjectEgressPolicyRevision.id == head.current_revision_id,
                    ProjectEgressPolicyRevision.project_id == self._project.id,
                )
            ),
        )

    async def read(self) -> dict[str, object]:
        revision = await self.current()
        if revision is None:
            return {
                "revision": 0,
                "revision_id": None,
                "mode": "current",
                "allowed_destination_revision_ids": [],
                "allowed_purposes": [],
                "policy_hash": None,
            }
        data = revision.policy_data
        destinations = data.get("allowed_destination_revision_ids")
        purposes = data.get("allowed_purposes")
        return {
            "revision": revision.revision,
            "revision_id": revision.id,
            "mode": revision.mode,
            "allowed_destination_revision_ids": (
                [str(value) for value in destinations]
                if isinstance(destinations, list) else []
            ),
            "allowed_purposes": (
                [str(value) for value in purposes] if isinstance(purposes, list) else []
            ),
            "policy_hash": revision.policy_hash,
        }

    async def put(
        self,
        *,
        expected_revision: int,
        mode: str,
        allowed_destination_revision_ids: list[str],
        allowed_purposes: list[str],
    ) -> ProjectEgressPolicyRevision:
        if expected_revision < 0:
            raise ValidationAppError("期望修订号不能为负")
        if mode not in EGRESS_MODES:
            raise ValidationAppError("不支持的外发模式", details={"code": "EGRESS_MODE_INVALID"})
        destinations = sorted({str(value) for value in allowed_destination_revision_ids})
        purposes = sorted({str(value) for value in allowed_purposes})
        if len(destinations) > _MAX_ITEMS or len(purposes) > _MAX_ITEMS:
            raise ValidationAppError("目的地与用途数量不能超过100")
        if any(item not in EGRESS_PURPOSES for item in purposes):
            raise ValidationAppError(
                "用途必须属于受支持的外发用途集合",
                details={"code": "EGRESS_PURPOSE_INVALID"},
            )
        if mode in {"current", "local_only"} and (destinations or purposes):
            raise ValidationAppError(
                "该外发模式不允许携带目的地或用途",
                details={"code": "EGRESS_MODE_PAYLOAD_INVALID"},
            )
        parsed: list[UUID] = []
        if mode == "allowlisted":
            if not destinations or not purposes:
                raise ValidationAppError(
                    "允许清单模式必须声明目的地与用途",
                    details={"code": "EGRESS_ALLOWLIST_INCOMPLETE"},
                )
            for value in destinations:
                try:
                    parsed.append(UUID(value))
                except ValueError as exc:
                    raise ValidationAppError(
                        "目的地修订编号不正确",
                        details={"code": "EGRESS_DESTINATION_INVALID"},
                    ) from exc
            rows = list(
                await self._session.scalars(
                    select(ProviderDestinationRevision).where(
                        ProviderDestinationRevision.id.in_(parsed),
                        ProviderDestinationRevision.workspace_id == self._project.workspace_id,
                    )
                )
            )
            if len(rows) != len(parsed):
                raise ValidationAppError(
                    "目的地必须来自本工作空间的可信登记",
                    details={"code": "EGRESS_DESTINATION_UNKNOWN"},
                )
            for row in rows:
                declared = {str(value) for value in row.purposes}
                if not set(purposes) <= declared:
                    raise ValidationAppError(
                        "目的地声明未覆盖全部允许用途",
                        details={"code": "EGRESS_PURPOSE_NOT_DECLARED"},
                    )
        digest = policy_hash(
            mode=mode, destination_ids=destinations, purposes=purposes,
        )
        policy_data = {
            "allowed_destination_revision_ids": destinations,
            "allowed_purposes": purposes,
        }
        head = await self.head()
        if head is None:
            if expected_revision != 0:
                raise ConflictError(
                    "项目尚未建立外发策略，请以期望修订0初始化",
                    details={"code": "EGRESS_HEAD_MISSING"},
                )
            revision = ProjectEgressPolicyRevision(
                project_id=self._project.id,
                revision=1,
                origin_expected_revision=0,
                mode=mode,
                policy_data=policy_data,
                policy_hash=digest,
                created_by=self._actor.id,
            )
            self._session.add(revision)
            await self._session.flush()
            self._session.add(
                ProjectEgressPolicyHead(
                    project_id=self._project.id,
                    current_revision_id=revision.id,
                    revision=1,
                )
            )
            await self._session.flush()
            return revision
        if head.revision != expected_revision:
            # A replay of the *same* committed basis must return the original
            # revision even though the head has since advanced.
            replay = cast(
                ProjectEgressPolicyRevision | None,
                await self._session.scalar(
                    select(ProjectEgressPolicyRevision).where(
                        ProjectEgressPolicyRevision.project_id == self._project.id,
                        ProjectEgressPolicyRevision.origin_expected_revision == expected_revision,
                    )
                ),
            )
            if replay is not None and replay.policy_hash == digest:
                return replay
            raise ConflictError(
                "外发策略已被更新，请刷新后重新确认",
                details={"code": "EGRESS_REVISION_CONFLICT", "current_revision": head.revision},
            )
        replay = cast(
            ProjectEgressPolicyRevision | None,
            await self._session.scalar(
                select(ProjectEgressPolicyRevision).where(
                    ProjectEgressPolicyRevision.project_id == self._project.id,
                    ProjectEgressPolicyRevision.origin_expected_revision == expected_revision,
                )
            ),
        )
        if replay is not None:
            if replay.policy_hash != digest:
                raise ConflictError(
                    "同一期望修订已提交了不同的外发策略",
                    details={"code": "EGRESS_POLICY_CONFLICT"},
                )
            return replay
        revision = ProjectEgressPolicyRevision(
            project_id=self._project.id,
            revision=head.revision + 1,
            origin_expected_revision=expected_revision,
            mode=mode,
            policy_data=policy_data,
            policy_hash=digest,
            created_by=self._actor.id,
        )
        self._session.add(revision)
        await self._session.flush()
        head.current_revision_id = revision.id
        head.revision = revision.revision
        await self._session.flush()
        return revision

    @staticmethod
    def created_at(revision: ProjectEgressPolicyRevision) -> datetime:
        return revision.created_at or datetime.now(UTC)


__all__ = ["ProjectDataPolicy", "policy_hash"]
