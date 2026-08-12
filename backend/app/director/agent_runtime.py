"""Shared text execution for Director Skills.

This module reuses the existing model profile, LiteLLM/provider router and
ProviderOperation lineage. It does not let an AgentRun mutate creative facts;
the caller must validate output and publish a proposal/version separately.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.creation.models import AgentRun, PlanningAuthorization
from app.creation.service import CreationService, _content_hash
from app.director.models import WorkflowStepRun
from app.director.registry import get_skill, get_template
from app.shared.errors import ConflictError, ValidationAppError


class DirectorAgentRuntime:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def run_text_skill(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        workflow_run_id: UUID,
        actor_id: UUID,
        step_key: str,
        skill_id: str,
        prompt: str,
        max_tokens: int,
        parse: Callable[[str], Any],
        idempotency_key: str,
        input_version_refs: list[str],
        provider_kind: str,
        provider_context: dict[str, object] | None = None,
    ) -> tuple[Any, AgentRun, WorkflowStepRun]:
        template = get_template("live_action_dialogue_short", "1.0.0")
        existing = (
            await self._session.execute(
                select(WorkflowStepRun).where(
                    WorkflowStepRun.workflow_run_id == workflow_run_id,
                    WorkflowStepRun.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise ConflictError(
                "Director Skill idempotency key already exists",
                details={
                    "code": "DIRECTOR_SKILL_ALREADY_EXECUTED",
                    "workflow_step_run_id": str(existing.id),
                    "status": existing.status,
                    "output_version_refs": existing.output_version_refs,
                },
            )
        step = next((item for item in template.steps if item.step_key == step_key), None)
        if step is None or step.skill_id != skill_id:
            raise ValidationAppError("skill is not allowed for the workflow step")
        skill = get_skill(skill_id, step.skill_version)
        if skill.execution_kind.value != "agent_run":
            raise ValidationAppError("workflow step is not an AgentRun skill")
        auth = PlanningAuthorization(
            project_id=project_id,
            user_id=actor_id,
            pricing_snapshot_id="director-text-v1",
            authorized_operations=["skill_execute"],
            estimated_max_amount=Decimal("1.00"),
            currency="USD",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        self._session.add(auth)
        await self._session.flush()
        agent = AgentRun(
            project_id=project_id,
            initiated_by=actor_id,
            planning_authorization_id=auth.id,
            operation="skill_execute",
            status="running",
            requested_capability=f"skill.{skill_id}.v1",
            prompt_version=f"{skill_id}-v1",
            output_schema_version=skill.output_schema,
            context_compiler_version="director-context-v1",
            input_hash=_content_hash({"prompt": prompt, "input_version_refs": input_version_refs}),
            context_hash=_content_hash(
                {
                    "workflow_run_id": str(workflow_run_id),
                    "template_version": template.version,
                    "skill_version": skill.version,
                }
            ),
            started_at=datetime.now(UTC),
        )
        self._session.add(agent)
        await self._session.flush()
        step_run = WorkflowStepRun(
            project_id=project_id,
            workflow_run_id=workflow_run_id,
            step_key=step_key,
            skill_id=skill.skill_id,
            skill_version=skill.version,
            execution_kind=skill.execution_kind.value,
            idempotency_key=idempotency_key,
            status="running",
            input_version_refs=input_version_refs,
            output_version_refs=[],
            agent_run_id=agent.id,
            started_at=datetime.now(UTC),
        )
        self._session.add(step_run)
        await self._session.flush()
        runner = CreationService(self._session)
        parsed: Any = None
        last_error: Exception | None = None
        for attempt_no in range(1, 4):
            attempt_prompt = prompt
            if last_error is not None:
                attempt_prompt += (
                    "\n\nThe prior output failed schema validation: "
                    f"{str(last_error)[:240]}. Return a complete replacement JSON object only."
                )
            try:
                parsed, _provider, _model, _cost = await runner._run_text_llm_attempt(
                    workspace_id=workspace_id,
                    project_id=project_id,
                    agent=agent,
                    attempt_no=attempt_no,
                    prompt=attempt_prompt,
                    kind=provider_kind,
                    max_tokens=max_tokens,
                    parse=parse,
                    brief=provider_context,
                )
            except Exception as exc:  # noqa: BLE001 - provider/schema boundary
                last_error = exc
                continue
            break
        finished = datetime.now(UTC)
        if parsed is None:
            agent.status = "failed"
            agent.stable_error_code = "DIRECTOR_SKILL_FAILED"
            agent.error_summary = str(last_error)[:200]
            agent.finished_at = finished
            step_run.status = "failed"
            step_run.error_code = "DIRECTOR_SKILL_FAILED"
            step_run.finished_at = finished
            await self._session.commit()
            raise ValidationAppError(
                f"Director Skill failed: {last_error}",
                details={
                    "code": "DIRECTOR_SKILL_FAILED",
                    "skill_id": skill_id,
                    "manual_ok": True,
                },
            ) from last_error
        agent.status = "succeeded"
        agent.finished_at = finished
        step_run.status = "succeeded"
        step_run.finished_at = finished
        return parsed, agent, step_run
