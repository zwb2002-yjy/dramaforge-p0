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

    async def generate_brief_agent(
        self,
        *,
        project_id: UUID,
        actor: User,
        idea: str,
        authorize: bool = True,
    ) -> CreativeBriefRevision:
        """BYOK text LLM → draft Brief revision. No Key → ValidationAppError (manual path)."""
        await self._projects.get_project_for_member(project_id=project_id, actor=actor)
        if not authorize:
            raise ValidationAppError(
                "planning authorization required for Agent Brief",
                details={"code": "PLANNING_AUTH_REQUIRED"},
            )
        idea = (idea or "").strip()
        if not idea:
            raise ValidationAppError("idea required for Agent Brief")
        from app.config import get_settings
        from app.providers.fake import FakeOpenAIAdapter

        settings = get_settings()
        adapter = get_openai_adapter(allow_live=True)
        # Product path: require live TEXT_LLM unless unit tests force Fake.
        if settings.app_env != "test" and not settings.text_llm_configured():
            raise ValidationAppError(
                "TEXT_LLM not configured; use manual Brief path",
                details={"code": "TEXT_LLM_NOT_CONFIGURED", "manual_ok": True},
            )
        if (
            settings.app_env != "test"
            and isinstance(adapter, FakeOpenAIAdapter)
            and not settings.text_llm_configured()
        ):
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
            authorized_operations=["generate_brief"],
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
            operation="generate_brief",
            status="running",
            requested_capability="text.brief.v1",
            prompt_version="brief-p0-v1",
            output_schema_version="brief-json-v1",
            context_compiler_version="ctx-p0-v1",
            input_hash=_content_hash({"idea": idea}),
            context_hash=_content_hash({"project_id": str(project_id)}),
            started_at=datetime.now(UTC),
        )
        self._session.add(agent)
        await self._session.flush()

        prompt = (
            "You are a short-drama creative assistant. Return ONLY compact JSON with keys "
            "logline, tone, audience (Chinese or English). Idea:\n"
            f"{idea}"
        )
        op = ProviderOperation(
            agent_run_id=agent.id,
            attempt_no=1,
            purpose="primary",
            operation_kind="text.brief.generate",
            actual_provider="openai",
            actual_model="text-llm",
            request_fingerprint=_content_hash({"prompt_chars": len(prompt)}),
            status="submitted",
            request_summary={"kind": "brief", "chars": len(prompt)},
            response_summary={},
            token_usage={},
            submitted_at=datetime.now(UTC),
        )
        self._session.add(op)
        await self._session.flush()

        try:
            created = await adapter.create({"prompt": prompt, "kind": "brief", "max_tokens": 400})
            remote_id = str(created.get("remote_task_id") or "")
            op.provider_operation_id = remote_id or None
            if created.get("status") == "failed":
                raise RuntimeError(str(created.get("error") or "text llm failed"))
            text_out = str(created.get("text") or "")
            if not text_out and hasattr(adapter, "poll"):
                polled = await adapter.poll(remote_id)
                text_out = str(polled.get("text") or "")
            # Fake adapter returns image-like payloads; synthesize brief for tests.
            if not text_out and type(adapter).__name__ == "FakeOpenAIAdapter":
                text_out = json.dumps(
                    {
                        "logline": f"Generated from: {idea[:120]}",
                        "tone": "cinematic",
                        "audience": "short-drama",
                    },
                    ensure_ascii=False,
                )
            parsed = _parse_brief_json(text_out, idea)
            op.status = "succeeded"
            op.completed_at = datetime.now(UTC)
            op.response_summary = {"logline_chars": len(str(parsed.get("logline", "")))}
            cost = await adapter.fetch_cost(remote_id) if remote_id else {"amount": 0}
            op.provider_cost = Decimal(str(cost.get("amount") or 0))
            op.token_usage = {
                "input_tokens": cost.get("input_tokens"),
                "output_tokens": cost.get("output_tokens"),
            }
            agent.status = "completed"
            agent.finished_at = datetime.now(UTC)
        except Exception as exc:  # noqa: BLE001 — map to agent failure
            op.status = "failed"
            op.completed_at = datetime.now(UTC)
            op.response_summary = {"error": str(exc)[:160]}
            agent.status = "failed"
            agent.stable_error_code = "TEXT_LLM_FAILED"
            agent.error_summary = str(exc)[:200]
            agent.finished_at = datetime.now(UTC)
            await self._session.commit()
            raise ValidationAppError(
                f"Agent Brief failed: {exc}",
                details={"code": "AGENT_BRIEF_FAILED", "manual_ok": True},
            ) from exc

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
        """BYOK text LLM → draft Plan (keyframe prompt + shot notes)."""
        await self._projects.get_project_for_member(project_id=project_id, actor=actor)
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
        logline = str((rev.brief or {}).get("logline") or "")
        from app.config import get_settings
        from app.providers.fake import FakeOpenAIAdapter

        settings = get_settings()
        adapter = get_openai_adapter(allow_live=True)
        if settings.app_env != "test" and not settings.text_llm_configured():
            raise ValidationAppError(
                "TEXT_LLM not configured; use manual Plan path",
                details={"code": "TEXT_LLM_NOT_CONFIGURED", "manual_ok": True},
            )

        from datetime import UTC, datetime, timedelta

        auth = PlanningAuthorization(
            project_id=project_id,
            user_id=actor.id,
            pricing_snapshot_id="p0-text-v1",
            authorized_operations=["generate_plan"],
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
            operation="generate_plan",
            status="running",
            requested_capability="text.plan.v1",
            prompt_version="plan-p0-v1",
            output_schema_version="plan-json-v1",
            context_compiler_version="ctx-p0-v1",
            input_hash=_content_hash({"brief": rev.content_hash}),
            context_hash=rev.content_hash,
            started_at=datetime.now(UTC),
        )
        self._session.add(agent)
        await self._session.flush()

        prompt = (
            "You are a short-drama planner. Return ONLY JSON with keys: "
            "prompt (keyframe visual prompt), shot_notes (short). Logline:\n"
            f"{logline}"
        )
        op = ProviderOperation(
            agent_run_id=agent.id,
            attempt_no=1,
            purpose="primary",
            operation_kind="text.plan.generate",
            actual_provider="openai",
            actual_model="text-llm",
            request_fingerprint=_content_hash({"prompt_chars": len(prompt)}),
            status="submitted",
            request_summary={"kind": "plan", "chars": len(prompt)},
            response_summary={},
            token_usage={},
            submitted_at=datetime.now(UTC),
        )
        self._session.add(op)
        await self._session.flush()

        try:
            created = await adapter.create({"prompt": prompt, "kind": "plan", "max_tokens": 500})
            remote_id = str(created.get("remote_task_id") or "")
            op.provider_operation_id = remote_id or None
            if created.get("status") == "failed":
                raise RuntimeError(str(created.get("error") or "text llm failed"))
            text_out = str(created.get("text") or "")
            if not text_out and type(adapter).__name__ == "FakeOpenAIAdapter":
                text_out = json.dumps(
                    {
                        "prompt": f"Cinematic opening keyframe for: {logline[:100]}",
                        "shot_notes": "wide establishing then push-in",
                    },
                    ensure_ascii=False,
                )
            plan_body = _parse_plan_json(text_out, logline)
            op.status = "succeeded"
            op.completed_at = datetime.now(UTC)
            op.response_summary = {"prompt_chars": len(str(plan_body.get("prompt", "")))}
            cost = await adapter.fetch_cost(remote_id) if remote_id else {"amount": 0}
            op.provider_cost = Decimal(str(cost.get("amount") or 0))
            agent.status = "completed"
            agent.finished_at = datetime.now(UTC)
        except Exception as exc:  # noqa: BLE001
            op.status = "failed"
            op.completed_at = datetime.now(UTC)
            agent.status = "failed"
            agent.error_summary = str(exc)[:200]
            agent.finished_at = datetime.now(UTC)
            await self._session.commit()
            raise ValidationAppError(
                f"Agent Plan failed: {exc}",
                details={"code": "AGENT_PLAN_FAILED", "manual_ok": True},
            ) from exc

        plan = await self.create_or_update_plan_manual(
            project_id=project_id,
            actor=actor,
            brief_revision_id=brief_revision_id,
            plan_body=plan_body,
        )
        # re-open for agent linkage (create_or_update commits)
        plan = await self._session.get(CreationPlan, plan.id)
        assert plan is not None
        plan.source_agent_run_id = agent.id
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
    return {
        "logline": logline,
        "tone": str(data.get("tone") or ""),
        "audience": str(data.get("audience") or ""),
        "incomplete": not bool(logline),
        "source": "agent",
    }


def _parse_plan_json(text: str, logline: str) -> dict[str, object]:
    data = _extract_json_object(text)
    prompt = str(data.get("prompt") or data.get("keyframe_prompt") or "").strip()
    if not prompt:
        prompt = f"Cinematic keyframe, 9:16, based on: {logline[:200]}"
    return {
        "prompt": prompt,
        "shot_notes": str(data.get("shot_notes") or data.get("notes") or ""),
        "source": "agent",
    }


def _extract_json_object(text: str) -> dict[str, object]:
    raw = (text or "").strip()
    if not raw:
        return {}
    try:
        val = json.loads(raw)
        if isinstance(val, dict):
            return val  # type: ignore[return-value]
    except json.JSONDecodeError:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        try:
            val = json.loads(raw[start : end + 1])
            if isinstance(val, dict):
                return val  # type: ignore[return-value]
        except json.JSONDecodeError:
            return {}
    return {}
