"""Creation experience: start_project + manual Brief/Plan (no text Provider without auth)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import User
from app.access.projects import ProjectService
from app.creation.models import CreationPlan, CreativeBrief, CreativeBriefRevision
from app.events.service import EventService
from app.shared.db import set_rls_context
from app.shared.enums import ExperienceMode
from app.shared.errors import ForbiddenError, NotFoundError, ValidationAppError


def _content_hash(payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class StartProjectResult:
    project_id: UUID
    experience_mode: str
    brief_id: UUID
    brief_revision_id: UUID
    event_id: UUID
    outbox_id: UUID
    text_provider_operations: int


@dataclass(frozen=True)
class ConfirmPlanResult:
    plan_id: UUID
    graph_id: UUID
    graph_version_id: UUID
    node_run_id: UUID
    materialization_ops: list[str]


class CreationService:
    """Stable Interface subset for S1/S2 manual path."""

    ALLOWED_MATERIALIZATION = frozenset(
        {
            "create_character_stub",
            "create_shot_stub",
            "bind_canonical_reference",
            "enqueue_keyframe",
        }
    )

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._projects = ProjectService(session)
        self._events = EventService(session)

    async def start_project(
        self,
        *,
        organization_id: UUID,
        name: str,
        aspect_ratio: str,
        actor: User,
        experience_mode: ExperienceMode = ExperienceMode.QUICK,
        idea: str = "",
    ) -> StartProjectResult:
        await set_rls_context(
            self._session,
            user_id=actor.id,
            organization_id=organization_id,
        )
        project = await self._projects.create_project(
            organization_id=organization_id,
            name=name,
            aspect_ratio=aspect_ratio,
            actor=actor,
            budget_limit=Decimal("0"),
        )
        await set_rls_context(
            self._session,
            user_id=actor.id,
            organization_id=organization_id,
            project_id=project.id,
        )
        await self._projects.set_experience_mode(
            project_id=project.id, actor=actor, mode=experience_mode
        )
        brief_body: dict[str, object] = {
            "logline": idea or "",
            "tone": "",
            "audience": "",
            "incomplete": True,
        }
        brief = CreativeBrief(
            project_id=project.id,
            created_by=actor.id,
        )
        self._session.add(brief)
        await self._session.flush()
        rev = CreativeBriefRevision(
            creative_brief_id=brief.id,
            project_id=project.id,
            revision_no=1,
            source_kind="user",
            source_text=idea or "(empty manual brief)",
            brief=brief_body,
            status="draft",
            content_hash=_content_hash(brief_body),
            created_by=actor.id,
        )
        self._session.add(rev)
        await self._session.flush()
        brief.current_revision_id = rev.id
        log, outbox = await self._events.append_with_outbox(
            project_id=project.id,
            aggregate_type="project",
            aggregate_id=project.id,
            event_type="project.started",
            topic="project.started",
            payload={
                "project_id": str(project.id),
                "experience_mode": experience_mode.value,
                "brief_revision_id": str(rev.id),
                "provider_calls": 0,
            },
            actor_id=actor.id,
        )
        await self._session.commit()
        return StartProjectResult(
            project_id=project.id,
            experience_mode=experience_mode.value,
            brief_id=brief.id,
            brief_revision_id=rev.id,
            event_id=log.event_id,
            outbox_id=outbox.id,
            text_provider_operations=0,
        )

    async def get_brief_revision(
        self, *, project_id: UUID, revision_id: UUID, actor: User
    ) -> CreativeBriefRevision:
        await self._projects.get_project_for_member(project_id=project_id, actor=actor)
        rev = await self._session.get(CreativeBriefRevision, revision_id)
        if rev is None or rev.project_id != project_id:
            raise NotFoundError("brief revision not found")
        return rev

    async def update_brief_manual(
        self,
        *,
        project_id: UUID,
        actor: User,
        logline: str,
        tone: str = "",
        audience: str = "",
    ) -> CreativeBriefRevision:
        await self._projects.get_project_for_member(project_id=project_id, actor=actor)
        brief = (
            await self._session.execute(
                select(CreativeBrief).where(CreativeBrief.project_id == project_id)
            )
        ).scalar_one_or_none()
        if brief is None:
            raise NotFoundError("brief not found")
        body: dict[str, object] = {
            "logline": logline,
            "tone": tone,
            "audience": audience,
            "incomplete": not bool(logline.strip()),
        }
        rev = CreativeBriefRevision(
            creative_brief_id=brief.id,
            project_id=project_id,
            revision_no=await self._next_brief_rev(brief.id),
            supersedes_revision_id=brief.current_revision_id,
            source_kind="user",
            source_text=logline,
            brief=body,
            status="draft",
            content_hash=_content_hash(body),
            created_by=actor.id,
        )
        self._session.add(rev)
        await self._session.flush()
        brief.current_revision_id = rev.id
        await self._session.commit()
        return rev

    async def confirm_brief(
        self, *, project_id: UUID, revision_id: UUID, actor: User
    ) -> CreativeBriefRevision:
        rev = await self.get_brief_revision(
            project_id=project_id, revision_id=revision_id, actor=actor
        )
        if rev.status == "confirmed":
            return rev
        logline = str((rev.brief or {}).get("logline", "")).strip()
        if not logline:
            raise ValidationAppError("brief logline required to confirm")
        from datetime import UTC, datetime

        rev.status = "confirmed"
        rev.confirmed_by = actor.id
        rev.confirmed_at = datetime.now(UTC)
        await self._events.append_with_outbox(
            project_id=project_id,
            aggregate_type="creative_brief_revision",
            aggregate_id=rev.id,
            event_type="brief.confirmed",
            topic="brief.confirmed",
            payload={"revision_id": str(rev.id)},
            actor_id=actor.id,
        )
        await self._session.commit()
        return rev

    async def create_or_update_plan_manual(
        self,
        *,
        project_id: UUID,
        actor: User,
        brief_revision_id: UUID,
        plan_body: dict[str, object],
    ) -> CreationPlan:
        await self._projects.get_project_for_member(project_id=project_id, actor=actor)
        rev = await self.get_brief_revision(
            project_id=project_id, revision_id=brief_revision_id, actor=actor
        )
        if rev.status != "confirmed":
            raise ValidationAppError("brief must be confirmed before plan")
        ctx = _content_hash({"brief": rev.content_hash, "plan": plan_body})
        existing = (
            await self._session.execute(
                select(CreationPlan)
                .where(CreationPlan.project_id == project_id)
                .where(CreationPlan.source_brief_revision_id == brief_revision_id)
                .where(CreationPlan.status == "draft")
            )
        ).scalar_one_or_none()
        if existing:
            existing.plan = plan_body
            existing.context_hash = ctx
            await self._session.commit()
            return existing
        plan = CreationPlan(
            project_id=project_id,
            source_brief_revision_id=brief_revision_id,
            plan=plan_body,
            context_hash=ctx,
            status="draft",
        )
        self._session.add(plan)
        await self._session.commit()
        return plan

    async def confirm_plan_and_materialize(
        self,
        *,
        project_id: UUID,
        plan_id: UUID,
        actor: User,
        materialization_ops: list[str] | None = None,
    ) -> ConfirmPlanResult:
        """Confirm plan and enqueue keyframe NodeRun (product path, not request-thread Adapter)."""
        from datetime import UTC, datetime

        from app.execution.product_path import enqueue_keyframe_after_plan

        await self._projects.get_project_for_member(project_id=project_id, actor=actor)
        plan = await self._session.get(CreationPlan, plan_id)
        if plan is None or plan.project_id != project_id:
            raise NotFoundError("plan not found")
        ops = materialization_ops or ["create_shot_stub", "enqueue_keyframe"]
        for op in ops:
            if op not in self.ALLOWED_MATERIALIZATION:
                raise ValidationAppError(f"materialization op not allowed: {op}")
        if plan.status != "confirmed":
            plan.status = "confirmed"
            plan.confirmed_by = actor.id
            plan.confirmed_at = datetime.now(UTC)
        result = await enqueue_keyframe_after_plan(
            self._session,
            project_id=project_id,
            user_id=actor.id,
            plan=plan,
            materialization_ops=ops,
        )
        plan.materialized_at = datetime.now(UTC)
        await self._events.append_with_outbox(
            project_id=project_id,
            aggregate_type="creation_plan",
            aggregate_id=plan.id,
            event_type="plan.confirmed_materialized",
            topic="node_run.enqueue",
            payload={
                "plan_id": str(plan.id),
                "node_run_id": str(result.node_run_id),
                "graph_version_id": str(result.graph_version_id),
            },
            actor_id=actor.id,
        )
        await self._session.commit()
        return ConfirmPlanResult(
            plan_id=plan.id,
            graph_id=result.graph_id,
            graph_version_id=result.graph_version_id,
            node_run_id=result.node_run_id,
            materialization_ops=ops,
        )

    async def _next_brief_rev(self, brief_id: UUID) -> int:
        rows = (
            await self._session.execute(
                select(CreativeBriefRevision.revision_no).where(
                    CreativeBriefRevision.creative_brief_id == brief_id
                )
            )
        ).scalars().all()
        return (max(rows) if rows else 0) + 1
