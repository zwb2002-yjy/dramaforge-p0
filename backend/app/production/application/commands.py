"""Shared production acceptance: ownership, replay, lock, validate, dispatch.

The caller owns commit. No director work, provider call or framework state may
participate in this application service's acceptance transaction.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import User
from app.access.projects import ProjectService
from app.assets.models import Shot
from app.contracts.domain_events import ExecutionAccepted
from app.contracts.production_commands import ExecutionBody, ExecutionPlanBody, ExecutionReceipt
from app.execution.models import NodeRun
from app.production.application.events import append_production_notice
from app.production.models import GraphVersion
from app.production.workbench_execution import (
    WorkbenchExecutionInput,
    WorkbenchExecutionService,
    workbench_request_hash,
)
from app.shared.errors import NotFoundError, ValidationAppError


def execution_input(
    project_id: UUID, shot_id: UUID, body: ExecutionPlanBody,
) -> WorkbenchExecutionInput:
    return WorkbenchExecutionInput(
        project_id=project_id, shot_id=shot_id, stage=body.stage,
        prompt=body.prompt, semantic_intent=body.semantic_intent, mode_id=body.mode_id,
        requested_model_id=body.requested_model_id,
        requested_binding_id=body.requested_binding_id,
        accept_approximations=body.accept_approximations,
        references=body.references, expected_shot_version=body.expected_shot_version,
    )


async def execution_receipt(session: AsyncSession, run: NodeRun) -> ExecutionReceipt:
    version = await session.get(GraphVersion, run.graph_version_id)
    if version is None:
        raise NotFoundError("Execution graph version not found")
    fingerprint = (run.input_snapshot or {}).get("plan_fingerprint")
    if not isinstance(fingerprint, str) or len(fingerprint) != 64:
        raise ValidationAppError(
            "Execution receipt has no valid frozen plan fingerprint",
            details={"code": "EXECUTION_RECEIPT_INVALID"},
        )
    return ExecutionReceipt(
        node_run_id=run.id, graph_id=version.graph_id, graph_version_id=run.graph_version_id,
        status=run.status, plan_fingerprint=fingerprint,
    )


class ProductionCommands:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def submit_user_execution(
        self, *, actor: User, project_id: UUID, shot_id: UUID,
        body: ExecutionBody, command_key: str | None,
    ) -> ExecutionReceipt:
        """Accept an explicit user command; actor comes from trusted auth context.

        An autonomous tool must not reinterpret this endpoint as a standing
        grant. Its separate authorization gate is mandatory before submission.
        """
        project = await ProjectService(self._session).get_project_for_owner(
            project_id=project_id, actor=actor,
        )
        service = WorkbenchExecutionService(self._session, user_id=actor.id)
        identity = workbench_request_hash(body.model_dump(mode="json"))
        await service.lock_command_scope(project_id=project_id)
        existing = await service.find_command_receipt(
            project_id=project_id, shot_id=shot_id, stage=body.stage,
            command_key=command_key, plan_fingerprint=body.plan_fingerprint,
            expected_request_hash=identity,
        )
        if existing is not None:
            return await execution_receipt(self._session, existing)
        shot = await self._session.get(
            Shot, shot_id, with_for_update=True, populate_existing=True,
        )
        if shot is None or shot.project_id != project_id:
            raise ValidationAppError("shot not found", details={"code": "SHOT_NOT_FOUND"})
        if shot.version != body.expected_shot_version:
            raise ValidationAppError(
                "shot changed since plan preview", details={"code": "SHOT_VERSION_MISMATCH"},
            )
        command_input = execution_input(project_id, shot_id, body)
        plan = await service.build_plan(project=project, execution_input=command_input)
        if plan.plan_fingerprint != body.plan_fingerprint:
            raise ValidationAppError(
                "plan fingerprint mismatch: inputs changed since preview",
                details={"code": "PLAN_FINGERPRINT_MISMATCH"},
            )
        if sorted(body.accepted_approximations) != sorted(plan.accepted_approximations):
            raise ValidationAppError(
                "accepted approximation set does not match the rebuilt plan",
                details={"code": "ACCEPTED_APPROXIMATIONS_MISMATCH"},
            )
        run = await service.create_and_dispatch(
            project=project, execution_input=command_input,
            idempotency_key_override=command_key, prepared_plan=plan, request_hash=identity,
        )
        await append_production_notice(
            self._session, project_id=project_id, actor_id=actor.id,
            notice=ExecutionAccepted(shot_id=shot_id, node_run_id=run.id),
        )
        return await execution_receipt(self._session, run)
