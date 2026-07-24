"""Creation experience: start_project + manual Brief/Plan (no text Provider without auth)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import User
from app.access.projects import ProjectService
from app.assets.models import Asset, Character, CharacterReference, Episode, Scene, Shot
from app.creation.models import (
    AgentRun,
    CreationPlan,
    CreativeBrief,
    CreativeBriefRevision,
    PlanningAuthorization,
)
from app.events.service import EventService
from app.execution.models import ProviderOperation
from app.providers.openai import get_openai_adapter
from app.shared.db import set_rls_context
from app.shared.enums import ExperienceMode
from app.shared.errors import NotFoundError, ValidationAppError


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
    graph_ids: list[UUID]
    graph_version_ids: list[UUID]
    node_run_ids: list[UUID]
    shot_ids: list[UUID]
    materialization_ops: list[str]


@dataclass(frozen=True)
class CreationStateResult:
    brief_revision: CreativeBriefRevision | None
    plan: CreationPlan | None


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

    async def get_creation_state(
        self, *, project_id: UUID, actor: User
    ) -> CreationStateResult:
        """Return the current Brief and its latest Plan for Quick workflow recovery."""
        await self._projects.get_project_for_member(project_id=project_id, actor=actor)
        brief = (
            await self._session.execute(
                select(CreativeBrief).where(CreativeBrief.project_id == project_id)
            )
        ).scalar_one_or_none()
        if brief is None or brief.current_revision_id is None:
            return CreationStateResult(brief_revision=None, plan=None)

        revision = await self._session.get(
            CreativeBriefRevision, brief.current_revision_id
        )
        if revision is None:
            raise ValidationAppError("current Brief revision is missing")
        plan = (
            await self._session.execute(
                select(CreationPlan)
                .where(CreationPlan.project_id == project_id)
                .where(CreationPlan.source_brief_revision_id == revision.id)
                .order_by(
                    CreationPlan.updated_at.desc(),
                    CreationPlan.created_at.desc(),
                    CreationPlan.id.desc(),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        return CreationStateResult(brief_revision=revision, plan=plan)

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
        return await self._create_or_update_plan(
            project_id=project_id,
            actor=actor,
            brief_revision_id=brief_revision_id,
            plan_body=plan_body,
            source_agent_run_id=None,
        )

    async def _create_or_update_plan(
        self,
        *,
        project_id: UUID,
        actor: User,
        brief_revision_id: UUID,
        plan_body: dict[str, object],
        source_agent_run_id: UUID | None,
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
                .order_by(
                    CreationPlan.updated_at.desc(),
                    CreationPlan.created_at.desc(),
                    CreationPlan.id.desc(),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if existing:
            if (
                source_agent_run_id is None
                and existing.source_agent_run_id is not None
            ):
                raise ValidationAppError(
                    "Agent Plan is already saved; manual save cannot overwrite it",
                    details={"code": "AGENT_PLAN_MANUAL_OVERWRITE_FORBIDDEN"},
                )
            from datetime import UTC, datetime

            existing.plan = plan_body
            existing.context_hash = ctx
            existing.source_agent_run_id = source_agent_run_id
            existing.updated_at = datetime.now(UTC)
            existing.version += 1
            await self._session.commit()
            return existing
        plan = CreationPlan(
            project_id=project_id,
            source_brief_revision_id=brief_revision_id,
            source_agent_run_id=source_agent_run_id,
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
        """Confirm Plan and materialize real Shots plus queued keyframe NodeRuns."""
        from datetime import UTC, datetime

        from app.execution.models import NodeRun
        from app.execution.product_path import enqueue_keyframe_after_plan
        from app.production.models import GraphVersion, ProductionGraph

        await self._projects.get_project_for_member(project_id=project_id, actor=actor)
        plan = await self._session.get(CreationPlan, plan_id)
        if plan is None or plan.project_id != project_id:
            raise NotFoundError("plan not found")
        if plan.source_agent_run_id is not None:
            raw_shots = plan.plan.get("shots")
            if not isinstance(raw_shots, list) or len(raw_shots) != 10:
                raise ValidationAppError(
                    "Legacy Agent Plan must be regenerated with exactly 10 shots",
                    details={
                        "code": "AGENT_PLAN_REGENERATION_REQUIRED",
                        "actual_shot_count": (
                            len(raw_shots) if isinstance(raw_shots, list) else 0
                        ),
                    },
                )
        ops = materialization_ops or ["create_shot_stub", "enqueue_keyframe"]
        for op in ops:
            if op not in self.ALLOWED_MATERIALIZATION:
                raise ValidationAppError(f"materialization op not allowed: {op}")
        existing_runs = list(
            (
                await self._session.execute(
                    select(NodeRun)
                    .where(NodeRun.project_id == project_id)
                    .order_by(NodeRun.created_at)
                )
            )
            .scalars()
            .all()
        )
        existing_runs = [
            run
            for run in existing_runs
            if str((run.input_snapshot or {}).get("plan_id") or "") == str(plan.id)
            and str((run.input_snapshot or {}).get("node_key") or "") == "keyframe"
        ]
        if plan.materialized_at is not None and existing_runs:
            graph_ids: list[UUID] = []
            graph_version_ids: list[UUID] = []
            materialized_shot_ids: list[UUID] = []
            for run in existing_runs:
                version = await self._session.get(GraphVersion, run.graph_version_id)
                graph = (
                    await self._session.get(ProductionGraph, version.graph_id)
                    if version is not None
                    else None
                )
                if graph is None:
                    raise ValidationAppError("materialized Plan is missing its production graph")
                graph_ids.append(graph.id)
                graph_version_ids.append(run.graph_version_id)
                raw_shot_id = str((run.input_snapshot or {}).get("shot_id") or "")
                if raw_shot_id:
                    materialized_shot_ids.append(UUID(raw_shot_id))
            return ConfirmPlanResult(
                plan_id=plan.id,
                graph_id=graph_ids[0],
                graph_version_id=graph_version_ids[0],
                node_run_id=existing_runs[0].id,
                graph_ids=graph_ids,
                graph_version_ids=graph_version_ids,
                node_run_ids=[run.id for run in existing_runs],
                shot_ids=materialized_shot_ids,
                materialization_ops=ops,
            )
        if plan.status != "confirmed":
            plan.status = "confirmed"
            plan.confirmed_by = actor.id
            plan.confirmed_at = datetime.now(UTC)
        shot_plans = _materialization_shots(plan.plan)
        episode_numbers = list(
            (
                await self._session.execute(
                    select(Episode.episode_number).where(Episode.project_id == project_id)
                )
            )
            .scalars()
            .all()
        )
        episode = Episode(
            project_id=project_id,
            episode_number=(max(episode_numbers) if episode_numbers else 0) + 1,
            title=_text(plan.plan.get("title"))[:160] or "Agent Plan",
            synopsis=_text(plan.plan.get("episode_summary"))
            or _text(plan.plan.get("shot_notes")),
        )
        self._session.add(episode)
        await self._session.flush()

        scene_map: dict[int, Scene] = {}
        results = []
        created_shot_ids: list[UUID] = []
        for sort_order, shot_plan in enumerate(shot_plans, start=1):
            scene_number = _positive_int(shot_plan.get("scene_number"), default=1)
            scene = scene_map.get(scene_number)
            if scene is None:
                scene = Scene(
                    episode_id=episode.id,
                    scene_number=scene_number,
                    location_name=_text(shot_plan.get("location"))[:160]
                    or "Unspecified location",
                    time_of_day=_text(shot_plan.get("time_of_day"))[:40] or "unspecified",
                    synopsis=_text(shot_plan.get("scene_summary"))
                    or _text(plan.plan.get("episode_summary")),
                )
                self._session.add(scene)
                await self._session.flush()
                scene_map[scene_number] = scene

            shot = Shot(
                project_id=project_id,
                scene_id=scene.id,
                shot_number=_positive_int(shot_plan.get("shot_number"), default=sort_order),
                shot_type=_text(shot_plan.get("shot_type"))[:40] or "medium",
                camera_move=_text(shot_plan.get("camera_move"))[:80] or "static",
                visual_description=_text(shot_plan.get("visual_description"))
                or _text(shot_plan.get("keyframe_prompt"))
                or f"Shot {sort_order}",
                dialogue=_text(shot_plan.get("dialogue")),
                duration_seconds=_duration(shot_plan.get("duration_seconds")),
                status="draft",
                sort_order=sort_order,
            )
            self._session.add(shot)
            await self._session.flush()
            created_shot_ids.append(shot.id)
            results.append(
                await enqueue_keyframe_after_plan(
                    self._session,
                    project_id=project_id,
                    user_id=actor.id,
                    plan=plan,
                    materialization_ops=ops,
                    shot_id=shot.id,
                    shot_plan=shot_plan,
                )
            )

        plan.materialized_at = datetime.now(UTC)
        for shot_id, result in zip(created_shot_ids, results, strict=True):
            await self._events.append_with_outbox(
                project_id=project_id,
                aggregate_type="creation_plan",
                aggregate_id=plan.id,
                event_type="plan.confirmed_materialized",
                topic="node_run.enqueue",
                payload={
                    "plan_id": str(plan.id),
                    "shot_id": str(shot_id),
                    "node_run_id": str(result.node_run_id),
                    "graph_version_id": str(result.graph_version_id),
                },
                actor_id=actor.id,
            )
        await self._session.commit()
        return ConfirmPlanResult(
            plan_id=plan.id,
            graph_id=results[0].graph_id,
            graph_version_id=results[0].graph_version_id,
            node_run_id=results[0].node_run_id,
            graph_ids=[result.graph_id for result in results],
            graph_version_ids=[result.graph_version_id for result in results],
            node_run_ids=[result.node_run_id for result in results],
            shot_ids=created_shot_ids,
            materialization_ops=ops,
        )

    async def generate_brief_agent(
        self,
        *,
        project_id: UUID,
        actor: User,
        idea: str,
        authorize: bool = True,
    ) -> CreativeBriefRevision:
        """BYOK text LLM → draft Brief revision. No Key → ValidationAppError (manual path)."""
        project = await self._projects.get_project_for_member(
            project_id=project_id,
            actor=actor,
        )
        if not authorize:
            raise ValidationAppError(
                "planning authorization required for Agent Brief",
                details={"code": "PLANNING_AUTH_REQUIRED"},
            )
        idea = (idea or "").strip()
        if not idea:
            raise ValidationAppError("idea required for Agent Brief")
        from app.config import get_settings
        settings = get_settings()
        if settings.app_env == "test":
            adapter = get_openai_adapter(allow_live=True)
        else:
            from app.providers.openai import get_openai_adapter_for_organization

            adapter = await get_openai_adapter_for_organization(
                self._session,
                organization_id=project.organization_id,
                allow_live=True,
            )
        # Product path: require live TEXT_LLM unless unit tests force Fake.
        if settings.app_env != "test" and not adapter.configured():
            raise ValidationAppError(
                "TEXT_LLM not configured; use manual Brief path",
                details={"code": "TEXT_LLM_NOT_CONFIGURED", "manual_ok": True},
            )
        brief_row = (
            await self._session.execute(
                select(CreativeBrief).where(CreativeBrief.project_id == project_id)
            )
        ).scalar_one_or_none()
        if brief_row is None:
            raise NotFoundError("brief not found")

        from datetime import UTC, datetime, timedelta

        auth = PlanningAuthorization(
            project_id=project_id,
            user_id=actor.id,
            pricing_snapshot_id="p0-text-v1",
            authorized_operations=["draft_brief"],
            estimated_max_amount=Decimal("1.00"),
            currency="USD",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        self._session.add(auth)
        await self._session.flush()

        agent = AgentRun(
            project_id=project_id,
            initiated_by=actor.id,
            planning_authorization_id=auth.id,
            operation="draft_brief",
            status="running",
            requested_capability="text.brief.v1",
            prompt_version="brief-p0-v2",
            output_schema_version="brief-json-v2",
            context_compiler_version="ctx-p0-v1",
            input_hash=_content_hash({"idea": idea}),
            context_hash=_content_hash({"project_id": str(project_id)}),
            started_at=datetime.now(UTC),
        )
        self._session.add(agent)
        await self._session.flush()

        prompt = (
            "You are the head writer for a premium vertical short drama. "
            "Develop the user's idea into a production-ready creative Brief. "
            "Return ONLY valid JSON, no markdown. Use the user's language. Required schema: "
            '{"title":"", "logline":"", "synopsis":"100-160 words", '
            '"protagonist":{"name":"","profile":"","goal":""}, '
            '"conflict":"", "stakes":"", "world":"", "tone":"", "audience":"", '
            '"visual_style":"specific cinematography, palette and lighting", '
            '"episode_hook":"strong final reveal or cliffhanger"}. '
            "Make every field concrete, concise, and internally consistent. Idea:\n"
            f"{idea.strip()}"
        )
        parsed: dict[str, object] | None = None
        last_error: Exception | None = None
        for attempt_no in range(1, 4):
            attempt_prompt = prompt
            if last_error is not None:
                attempt_prompt += (
                    "\n\nYour previous response failed validation: "
                    f"{str(last_error)[:180]}. Return a complete replacement JSON object "
                    "only. Do not explain the correction. Include every required top-level "
                    "field and protagonist.name, protagonist.profile, and protagonist.goal."
                )
            op = ProviderOperation(
                agent_run_id=agent.id,
                attempt_no=attempt_no,
                purpose="primary",
                operation_kind="text.brief.generate",
                actual_provider="openai",
                actual_model="text-llm",
                request_fingerprint=_content_hash(
                    {"prompt_chars": len(attempt_prompt), "attempt": attempt_no}
                ),
                status="submitted",
                request_summary={
                    "kind": "brief",
                    "chars": len(attempt_prompt),
                    "retry": attempt_no > 1,
                },
                response_summary={},
                token_usage={},
                submitted_at=datetime.now(UTC),
            )
            self._session.add(op)
            await self._session.flush()
            remote_id = ""
            text_out = ""
            try:
                created = await adapter.create(
                    {
                        "prompt": attempt_prompt,
                        "kind": "brief",
                        "idea": idea,
                        "max_tokens": 2400,
                    }
                )
                remote_id = str(created.get("remote_task_id") or "")
                op.provider_operation_id = remote_id or None
                if created.get("status") == "failed":
                    raise RuntimeError(str(created.get("error") or "text llm failed"))
                text_out = str(created.get("text") or "")
                if not text_out and hasattr(adapter, "poll"):
                    polled = await adapter.poll(remote_id)
                    text_out = str(polled.get("text") or "")
                parsed = _parse_brief_json(text_out, idea)
            except Exception as exc:  # noqa: BLE001 - provider/schema boundary
                last_error = exc
                op.status = "failed"
                op.completed_at = datetime.now(UTC)
                op.response_summary = {
                    "error": str(exc)[:160],
                    "response_chars": len(text_out),
                }
                cost = await adapter.fetch_cost(remote_id) if remote_id else {"amount": 0}
                op.provider_cost = Decimal(str(cost.get("amount") or 0))
                op.token_usage = {
                    "input_tokens": cost.get("input_tokens"),
                    "output_tokens": cost.get("output_tokens"),
                }
                continue
            op.status = "succeeded"
            op.completed_at = datetime.now(UTC)
            op.response_summary = {"logline_chars": len(str(parsed.get("logline", "")))}
            cost = await adapter.fetch_cost(remote_id) if remote_id else {"amount": 0}
            op.provider_cost = Decimal(str(cost.get("amount") or 0))
            op.token_usage = {
                "input_tokens": cost.get("input_tokens"),
                "output_tokens": cost.get("output_tokens"),
            }
            break

        if parsed is None:
            assert last_error is not None
            agent.status = "failed"
            agent.stable_error_code = "TEXT_LLM_FAILED"
            agent.error_summary = str(last_error)[:200]
            agent.finished_at = datetime.now(UTC)
            await self._session.commit()
            raise ValidationAppError(
                f"Agent Brief failed: {last_error}",
                details={"code": "AGENT_BRIEF_FAILED", "manual_ok": True},
            ) from last_error
        agent.status = "succeeded"
        agent.finished_at = datetime.now(UTC)

        rev = CreativeBriefRevision(
            creative_brief_id=brief_row.id,
            project_id=project_id,
            revision_no=await self._next_brief_rev(brief_row.id),
            supersedes_revision_id=brief_row.current_revision_id,
            source_kind="agent",
            source_agent_run_id=agent.id,
            source_text=idea,
            brief=parsed,
            status="draft",
            content_hash=_content_hash(parsed),
            created_by=actor.id,
        )
        self._session.add(rev)
        await self._session.flush()
        brief_row.current_revision_id = rev.id
        agent.result_brief_revision_id = rev.id
        agent.target_brief_revision_id = rev.id
        await self._events.append_with_outbox(
            project_id=project_id,
            aggregate_type="creative_brief_revision",
            aggregate_id=rev.id,
            event_type="brief.agent_drafted",
            topic="brief.agent_drafted",
            payload={"revision_id": str(rev.id), "agent_run_id": str(agent.id)},
            actor_id=actor.id,
        )
        await self._session.commit()
        return rev

    async def generate_plan_agent(
        self,
        *,
        project_id: UUID,
        actor: User,
        brief_revision_id: UUID,
        authorize: bool = True,
    ) -> CreationPlan:
        """BYOK text LLM → draft Plan with ten production-ready storyboard Shots."""
        project = await self._projects.get_project_for_member(
            project_id=project_id,
            actor=actor,
        )
        if not authorize:
            raise ValidationAppError(
                "planning authorization required for Agent Plan",
                details={"code": "PLANNING_AUTH_REQUIRED"},
            )
        rev = await self.get_brief_revision(
            project_id=project_id, revision_id=brief_revision_id, actor=actor
        )
        if rev.status != "confirmed":
            raise ValidationAppError("brief must be confirmed before Agent Plan")
        brief_body = dict(rev.brief or {})
        if rev.source_kind == "agent":
            missing = _missing_agent_brief_fields(brief_body)
            if missing:
                raise ValidationAppError(
                    "Legacy Agent Brief must be regenerated before Agent Plan",
                    details={
                        "code": "AGENT_BRIEF_REGENERATION_REQUIRED",
                        "missing_fields": missing,
                    },
                )
        logline = str(brief_body.get("logline") or "")
        canonical_lead = (
            await self._session.execute(
                select(Asset.name, Character.locked_prompt)
                .join(Character, Character.id == Asset.id)
                .join(CharacterReference, CharacterReference.character_id == Character.id)
                .where(Asset.project_id == project_id)
                .where(CharacterReference.is_canonical.is_(True))
                .limit(1)
            )
        ).one_or_none()
        canonical_lead_name = str(canonical_lead[0]).strip() if canonical_lead else ""
        canonical_lead_prompt = str(canonical_lead[1]).strip() if canonical_lead else ""
        from app.config import get_settings

        settings = get_settings()
        if settings.app_env == "test":
            adapter = get_openai_adapter(allow_live=True)
        else:
            from app.providers.openai import get_openai_adapter_for_organization

            adapter = await get_openai_adapter_for_organization(
                self._session,
                organization_id=project.organization_id,
                allow_live=True,
            )
        if settings.app_env != "test" and not adapter.configured():
            raise ValidationAppError(
                "TEXT_LLM not configured; use manual Plan path",
                details={"code": "TEXT_LLM_NOT_CONFIGURED", "manual_ok": True},
            )

        from datetime import UTC, datetime, timedelta

        auth = PlanningAuthorization(
            project_id=project_id,
            user_id=actor.id,
            pricing_snapshot_id="p0-text-v1",
            authorized_operations=["draft_plan"],
            estimated_max_amount=Decimal("1.00"),
            currency="USD",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        self._session.add(auth)
        await self._session.flush()
        agent = AgentRun(
            project_id=project_id,
            initiated_by=actor.id,
            planning_authorization_id=auth.id,
            operation="draft_plan",
            status="running",
            requested_capability="text.plan.v1",
            prompt_version="plan-p0-v2",
            output_schema_version="plan-json-v2",
            context_compiler_version="ctx-p0-v1",
            input_hash=_content_hash({"brief": rev.content_hash}),
            context_hash=rev.content_hash,
            started_at=datetime.now(UTC),
        )
        self._session.add(agent)
        await self._session.flush()

        prompt = (
            "You are a short-drama director and storyboard artist. Convert the confirmed "
            "Brief below into exactly 10 sequential shots for a 9:16 episode. Return ONLY "
            "valid JSON, no markdown. Use the Brief's language. Required schema: "
            '{"title":"", "episode_summary":"", "visual_bible":{'
            '"aspect_ratio":"9:16","style":"","color_palette":"","lighting":"",'
            '"character_continuity":"","negative_prompt":""}, "shots":[{'
            '"shot_number":1,"scene_number":1,"location":"","time_of_day":"",'
            '"shot_type":"wide|medium|close|insert|over_shoulder",'
            '"camera_move":"static|push_in|pull_out|pan|tracking|handheld",'
            '"visual_description":"specific subject action, composition and story beat",'
            '"dialogue":"","keyframe_prompt":"standalone image-generation prompt including '
            'character, action, location, composition, lens, lighting, palette, 9:16",'
            '"lead_identity_required":true,'
            '"duration_seconds":3.0}]}. Each shot must advance the story, preserve character '
            "wardrobe/appearance, vary shot scale, and end shot 10 on the episode hook. "
            "For every shot, lead_identity_required must be a JSON boolean. Set it true only "
            "when the canonical lead must be visibly identifiable in the generated frame; set "
            "it false for inserts, empty environments, screens, back-of-head shots, or shots "
            "of other characters where a lead-face comparison is not applicable. "
            "Keep each visual_description and keyframe_prompt concise so the complete JSON "
            "fits in one response. The shots array must contain items 1 through 10 exactly. "
            + (
                "A canonical lead is registered. Use this exact identity whenever "
                "lead_identity_required is true. Include the locked identity description "
                f"verbatim in each matching keyframe_prompt. Name: {canonical_lead_name}. "
                f"Locked identity: {canonical_lead_prompt}. "
                if canonical_lead_name and canonical_lead_prompt
                else ""
            )
            + "Brief:\n"
            f"{json.dumps(brief_body, ensure_ascii=False)}"
        )
        plan_body: dict[str, object] | None = None
        last_error = None
        for attempt_no in range(1, 4):
            attempt_prompt = prompt
            if last_error is not None:
                attempt_prompt += (
                    "\n\nYour previous response failed validation: "
                    f"{str(last_error)[:180]}. Return a complete replacement JSON object "
                    "only. Do not explain the correction. Verify that shots is an array of "
                    "exactly 10 objects before responding."
                )
            op = ProviderOperation(
                agent_run_id=agent.id,
                attempt_no=attempt_no,
                purpose="primary",
                operation_kind="text.plan.generate",
                actual_provider="openai",
                actual_model="text-llm",
                request_fingerprint=_content_hash(
                    {"prompt_chars": len(attempt_prompt), "attempt": attempt_no}
                ),
                status="submitted",
                request_summary={
                    "kind": "plan",
                    "chars": len(attempt_prompt),
                    "retry": attempt_no > 1,
                },
                response_summary={},
                token_usage={},
                submitted_at=datetime.now(UTC),
            )
            self._session.add(op)
            await self._session.flush()
            remote_id = ""
            text_out = ""
            try:
                created = await adapter.create(
                    {
                        "prompt": attempt_prompt,
                        "kind": "plan",
                        "brief": brief_body,
                        "max_tokens": 6000,
                    }
                )
                remote_id = str(created.get("remote_task_id") or "")
                op.provider_operation_id = remote_id or None
                if created.get("status") == "failed":
                    raise RuntimeError(str(created.get("error") or "text llm failed"))
                text_out = str(created.get("text") or "")
                if not text_out and hasattr(adapter, "poll"):
                    polled = await adapter.poll(remote_id)
                    text_out = str(polled.get("text") or "")
                plan_body = _parse_plan_json(text_out, logline)
            except Exception as exc:  # noqa: BLE001 - provider/schema boundary
                last_error = exc
                op.status = "failed"
                op.completed_at = datetime.now(UTC)
                op.response_summary = {
                    "error": str(exc)[:160],
                    "response_chars": len(text_out),
                }
                cost = await adapter.fetch_cost(remote_id) if remote_id else {"amount": 0}
                op.provider_cost = Decimal(str(cost.get("amount") or 0))
                op.token_usage = {
                    "input_tokens": cost.get("input_tokens"),
                    "output_tokens": cost.get("output_tokens"),
                }
                continue
            op.status = "succeeded"
            op.completed_at = datetime.now(UTC)
            op.response_summary = {"prompt_chars": len(str(plan_body.get("prompt", "")))}
            cost = await adapter.fetch_cost(remote_id) if remote_id else {"amount": 0}
            op.provider_cost = Decimal(str(cost.get("amount") or 0))
            op.token_usage = {
                "input_tokens": cost.get("input_tokens"),
                "output_tokens": cost.get("output_tokens"),
            }
            break

        if plan_body is None:
            assert last_error is not None
            agent.status = "failed"
            agent.stable_error_code = "TEXT_LLM_FAILED"
            agent.error_summary = str(last_error)[:200]
            agent.finished_at = datetime.now(UTC)
            await self._session.commit()
            raise ValidationAppError(
                f"Agent Plan failed: {last_error}",
                details={"code": "AGENT_PLAN_FAILED", "manual_ok": True},
            ) from last_error
        agent.status = "succeeded"
        agent.finished_at = datetime.now(UTC)

        plan = await self._create_or_update_plan(
            project_id=project_id,
            actor=actor,
            brief_revision_id=brief_revision_id,
            plan_body=plan_body,
            source_agent_run_id=agent.id,
        )
        agent.result_plan_id = plan.id
        agent.target_plan_id = plan.id
        await self._session.commit()
        return plan

    async def _next_brief_rev(self, brief_id: UUID) -> int:
        rows = (
            await self._session.execute(
                select(CreativeBriefRevision.revision_no).where(
                    CreativeBriefRevision.creative_brief_id == brief_id
                )
            )
        ).scalars().all()
        return (max(rows) if rows else 0) + 1


def _parse_brief_json(text: str, idea: str) -> dict[str, object]:
    data = _extract_json_object(text)
    logline = str(data.get("logline") or data.get("synopsis") or "").strip()
    if not logline:
        logline = idea[:500]
    protagonist_raw = data.get("protagonist")
    if isinstance(protagonist_raw, dict):
        protagonist = {
            "name": _text(protagonist_raw.get("name")),
            "profile": _text(
                protagonist_raw.get("profile") or protagonist_raw.get("description")
            ),
            "goal": _text(protagonist_raw.get("goal")),
        }
    else:
        protagonist = {
            "name": "",
            "profile": _text(protagonist_raw),
            "goal": _text(data.get("goal")),
        }
    brief = {
        "title": _text(data.get("title")) or "Untitled short drama",
        "logline": logline,
        "synopsis": _text(data.get("synopsis")) or logline,
        "protagonist": protagonist,
        "conflict": _text(data.get("conflict")),
        "stakes": _text(data.get("stakes")),
        "world": _text(data.get("world") or data.get("setting")),
        "tone": _text(data.get("tone")),
        "audience": _text(data.get("audience")),
        "visual_style": _text(data.get("visual_style") or data.get("visual_direction")),
        "episode_hook": _text(data.get("episode_hook") or data.get("hook")),
        "incomplete": not bool(logline),
        "source": "agent",
    }
    missing = _missing_agent_brief_fields(brief)
    if missing:
        raise ValueError(
            "Agent Brief is incomplete; missing fields: " + ", ".join(missing)
        )
    return brief


def _parse_plan_json(text: str, logline: str) -> dict[str, object]:
    data = _extract_json_object(text)
    raw_shots = data.get("shots")
    if not isinstance(raw_shots, list) or len(raw_shots) != 10:
        raise ValueError("Agent Plan must contain exactly 10 structured shots")
    shots = [
        _normalize_plan_shot(raw, index)
        for index, raw in enumerate(raw_shots, start=1)
    ]
    prompt = _text(data.get("prompt") or data.get("keyframe_prompt"))
    if not prompt:
        prompt = _text(shots[0].get("keyframe_prompt"))
    if not prompt:
        raise ValueError("Agent Plan shot 1 is missing keyframe_prompt")
    visual_bible_raw = data.get("visual_bible")
    visual_bible = visual_bible_raw if isinstance(visual_bible_raw, dict) else {}
    return {
        "title": _text(data.get("title")) or "Episode 1",
        "episode_summary": _text(data.get("episode_summary")) or logline,
        "visual_bible": {
            "aspect_ratio": _text(visual_bible.get("aspect_ratio")) or "9:16",
            "style": _text(visual_bible.get("style")),
            "color_palette": _text(visual_bible.get("color_palette")),
            "lighting": _text(visual_bible.get("lighting")),
            "character_continuity": _text(
                visual_bible.get("character_continuity")
            ),
            "negative_prompt": _text(visual_bible.get("negative_prompt")),
        },
        "shots": shots,
        "prompt": prompt,
        "shot_notes": _text(data.get("shot_notes") or data.get("notes"))
        or f"10-shot storyboard for: {logline[:160]}",
        "source": "agent",
    }


def _normalize_plan_shot(raw: object, index: int) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise ValueError(f"Agent Plan shot {index} must be an object")
    visual = _text(raw.get("visual_description") or raw.get("visual"))
    keyframe_prompt = _text(raw.get("keyframe_prompt") or raw.get("prompt"))
    if not visual:
        raise ValueError(f"Agent Plan shot {index} is missing visual_description")
    if not keyframe_prompt:
        raise ValueError(f"Agent Plan shot {index} is missing keyframe_prompt")
    lead_identity_required = raw.get("lead_identity_required")
    if not isinstance(lead_identity_required, bool):
        raise ValueError(
            f"Agent Plan shot {index} must set lead_identity_required to a JSON boolean"
        )
    return {
        "shot_number": _positive_int(raw.get("shot_number"), default=index),
        "scene_number": _positive_int(raw.get("scene_number"), default=1),
        "location": _text(raw.get("location")) or "Unspecified location",
        "time_of_day": _text(raw.get("time_of_day")) or "unspecified",
        "shot_type": _text(raw.get("shot_type")) or "medium",
        "camera_move": _text(raw.get("camera_move")) or "static",
        "visual_description": visual,
        "dialogue": _text(raw.get("dialogue")),
        "keyframe_prompt": keyframe_prompt,
        "lead_identity_required": lead_identity_required,
        "duration_seconds": float(_duration(raw.get("duration_seconds"))),
    }


def _missing_agent_brief_fields(brief: dict[str, object]) -> list[str]:
    required = (
        "title",
        "logline",
        "synopsis",
        "conflict",
        "stakes",
        "world",
        "tone",
        "audience",
        "visual_style",
        "episode_hook",
    )
    missing = [field for field in required if not _text(brief.get(field))]
    protagonist = brief.get("protagonist")
    if not isinstance(protagonist, dict):
        return [*missing, "protagonist"]
    for field in ("name", "profile", "goal"):
        if not _text(protagonist.get(field)):
            missing.append(f"protagonist.{field}")
    return missing


def _materialization_shots(plan: dict[str, object]) -> list[dict[str, object]]:
    raw_shots = plan.get("shots")
    if isinstance(raw_shots, list) and raw_shots:
        return [
            _normalize_materialization_shot(raw, index)
            for index, raw in enumerate(raw_shots, start=1)
        ]
    prompt = _text(plan.get("prompt")) or "Cinematic opening keyframe, 9:16"
    return [
        {
            "shot_number": 1,
            "scene_number": 1,
            "location": "Unspecified location",
            "time_of_day": "unspecified",
            "shot_type": "medium",
            "camera_move": "static",
            "visual_description": _text(plan.get("shot_notes")) or prompt,
            "dialogue": "",
            "keyframe_prompt": prompt,
            "duration_seconds": 3.0,
        }
    ]


def _normalize_materialization_shot(raw: object, index: int) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise ValidationAppError(f"Plan shot {index} must be an object")
    visual = _text(raw.get("visual_description") or raw.get("visual"))
    prompt = _text(raw.get("keyframe_prompt") or raw.get("prompt")) or visual
    if not visual or not prompt:
        raise ValidationAppError(
            f"Plan shot {index} requires visual_description and keyframe_prompt"
        )
    return {
        **raw,
        "shot_number": _positive_int(raw.get("shot_number"), default=index),
        "scene_number": _positive_int(raw.get("scene_number"), default=1),
        "visual_description": visual,
        "keyframe_prompt": prompt,
        # Manual plans predate this field. Omitted values remain fail-closed.
        "lead_identity_required": (
            raw["lead_identity_required"]
            if isinstance(raw.get("lead_identity_required"), bool)
            else True
        ),
    }


def _text(value: object) -> str:
    return str(value or "").strip()


def _positive_int(value: object, *, default: int) -> int:
    try:
        parsed = int(cast(Any, value))
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _duration(value: object) -> Decimal:
    try:
        duration = Decimal(str(value if value is not None else 3))
    except (InvalidOperation, ValueError):
        duration = Decimal("3")
    return min(max(duration, Decimal("0.5")), Decimal("30"))


def _extract_json_object(text: str) -> dict[str, object]:
    raw = (text or "").strip()
    if not raw:
        return {}
    try:
        val = json.loads(raw)
        if isinstance(val, dict):
            return {str(key): value for key, value in val.items()}
    except json.JSONDecodeError:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        try:
            val = json.loads(raw[start : end + 1])
            if isinstance(val, dict):
                return {str(key): value for key, value in val.items()}
        except json.JSONDecodeError:
            return {}
    return {}
