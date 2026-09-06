"""Editing -> Production Repair routing (V1 G6C).

The Director first decides whether an issue found in an EditSession can be
fixed inside the timeline.  When the timeline can solve the issue, the normal
editing suggestion service produces a typed timeline proposal.  When it
cannot, this service persists a *proposal-only* production repair proposal
scoped to the EditSession.  It never applies the repair and never dispatches a
NodeRun / ProviderOperation.
"""

from __future__ import annotations

import re
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import User
from app.access.projects import ProjectService
from app.assets.models import Shot
from app.director.assistant_models import DirectorThread
from app.director.editing_suggestion import _timeline_context
from app.director.proposal_models import DirectorProposal, DirectorProposalItem
from app.editing.adapter import EditingAdapter
from app.editing.models import EditSession
from app.shared.errors import ConflictError


class EditingRepairRoutingRequest(BaseModel):
    """No timeline/lineage/provider fields are accepted from the client."""

    model_config = ConfigDict(extra="forbid")

    expected_session_version: int = Field(ge=1)
    user_instruction: str = Field(default="", max_length=4000)


class EditingRepairRoutingRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    session_id: UUID
    session_version: int = Field(ge=1)
    can_fix_in_timeline: bool
    proposal_id: UUID | None = None
    item_id: UUID | None = None
    shot_ids: list[str] = Field(default_factory=list)
    reason: str | None = None


_REPAIR_SIGNAL_PATTERNS = (
    re.compile(r"补拍|重拍|重新拍|reshoot|re[- ]?shoot", re.IGNORECASE),
    re.compile(r"表演不行|表演不到位|表演不像|演技差|identity|脸不对|不像本人", re.IGNORECASE),
    re.compile(r"无法在时间线|不能靠剪辑|无法通过剪辑|必须回炉|需要生产修复", re.IGNORECASE),
)


def _has_repair_signal(user_instruction: str) -> bool:
    return any(pattern.search(user_instruction) for pattern in _REPAIR_SIGNAL_PATTERNS)


class EditingRepairRoutingService:
    """Route one editing issue to a timeline proposal or a repair proposal."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def route(
        self,
        *,
        project_id: UUID,
        session_id: UUID,
        actor: User,
        request: EditingRepairRoutingRequest,
    ) -> EditingRepairRoutingRead:
        project = await ProjectService(self._session).get_project_for_owner(
            project_id=project_id, actor=actor
        )
        adapter = EditingAdapter(self._session)
        edit_session = await adapter.load_timeline(
            project_id=project.id,
            session_id=session_id,
        )
        if edit_session.version != request.expected_session_version:
            raise ConflictError(
                "edit session version conflict; repair routing must use current server truth",
                details={
                    "code": "EDITING_REPAIR_ROUTING_STALE",
                    "expected_version": request.expected_session_version,
                    "actual_version": edit_session.version,
                },
            )

        context = _timeline_context(dict(edit_session.timeline or {}))
        clip_shot_ids: list[str] = []
        for clip in context.clips:
            if clip.shot_id and clip.shot_id not in clip_shot_ids:
                clip_shot_ids.append(clip.shot_id)

        explicit_signal = _has_repair_signal(request.user_instruction)
        shot_ids: list[str] = list(clip_shot_ids) if explicit_signal else []
        reason = (
            "导演判断该问题无法在时间线内解决，需要回到镜头生产层做 Repair。"
            if explicit_signal
            else None
        )

        if not explicit_signal and clip_shot_ids:
            # Server-fact check: a clip that references a Shot without an
            # official formal video cannot be healed by reordering/trimming
            # clips; the Shot itself must be repaired first.
            try:
                uuids = [UUID(shot_id) for shot_id in clip_shot_ids]
            except ValueError:
                uuids = []
            if uuids:
                rows = (
                    await self._session.execute(
                        select(Shot.id, Shot.formal_video_artifact_id).where(
                            Shot.project_id == project.id,
                            Shot.id.in_(uuids),
                        )
                    )
                ).all()
                formal_by_shot = {row[0]: row[1] for row in rows}
                shot_ids = [
                    shot_id
                    for shot_id in clip_shot_ids
                    if formal_by_shot.get(UUID(shot_id)) is None
                ]
                if shot_ids:
                    reason = (
                        "时间线中的镜头缺少正式视频 Artifact；重排与修剪无法解决，"
                        "必须先在 Shot 生产层完成 Repair。"
                    )

        if not shot_ids:
            return EditingRepairRoutingRead(
                project_id=project.id,
                session_id=edit_session.id,
                session_version=edit_session.version,
                can_fix_in_timeline=True,
                shot_ids=[],
                reason="该问题可以在当前 EditSession 时间线内处理，无需生产 Repair。",
            )

        # Re-read the persisted version after the server-fact query so a
        # concurrent timeline save cannot make this proposal stale.
        latest_version = await self._session.scalar(
            select(EditSession.version).where(
                EditSession.project_id == project.id,
                EditSession.id == edit_session.id,
            )
        )
        if latest_version != edit_session.version:
            raise ConflictError(
                "edit session changed while repair routing was generated",
                details={
                    "code": "EDITING_REPAIR_ROUTING_STALE",
                    "expected_version": edit_session.version,
                    "actual_version": latest_version,
                },
            )

        thread = await self._session.scalar(
            select(DirectorThread).where(
                DirectorThread.project_id == project.id,
                DirectorThread.scope_type == "project",
                DirectorThread.scope_entity_id == project.id,
            )
        )
        if thread is None:
            thread = DirectorThread(
                project_id=project.id,
                scope_type="project",
                scope_entity_id=project.id,
                created_by=actor.id,
            )
            self._session.add(thread)
            await self._session.flush()

        proposal = DirectorProposal(
            project_id=project.id,
            thread_id=thread.id,
            scope_type="edit_session",
            scope_entity_id=edit_session.id,
            status="pending",
            created_by=actor.id,
        )
        self._session.add(proposal)
        await self._session.flush()
        item = DirectorProposalItem(
            proposal_id=proposal.id,
            project_id=project.id,
            command="editing.repair_proposal",
            payload={
                "edit_session_id": str(edit_session.id),
                "shot_ids": shot_ids,
                "no_auto_execute": True,
            },
            expected_target_version=edit_session.version,
            rationale=reason or "Repair Proposal",
            benefit="只提出生产层修复范围，不自动执行任何 Repair。",
            cost="需要人工到 Shot/审片 Repair 计划中确认并执行。",
            risk="Repair Proposal 本身不改变时间线、Shot、NodeRun 或 Provider 事实。",
            impact="仅记录 production repair 需求；timeline 与 production lineage 保持只读。",
            status="pending",
        )
        self._session.add(item)
        await self._session.flush()
        await self._session.commit()

        return EditingRepairRoutingRead(
            project_id=project.id,
            session_id=edit_session.id,
            session_version=edit_session.version,
            can_fix_in_timeline=False,
            proposal_id=proposal.id,
            item_id=item.id,
            shot_ids=shot_ids,
            reason=reason,
        )


__all__ = [
    "EditingRepairRoutingRead",
    "EditingRepairRoutingRequest",
    "EditingRepairRoutingService",
    "_has_repair_signal",
]
