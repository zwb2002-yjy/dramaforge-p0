"""Worker-side BusinessFlow advancement through the controlled tool registry.

The worker is the only driver of flow steps: it resolves the persisted project
scope, adopts one non-terminal instance and executes dependency-ready steps via
the existing ``ToolExecutor`` allowlist. It never creates a Turn, a NodeRun or a
Provider operation on its own, and it never replays a lost attempt.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project, User
from app.config import Settings
from app.director.agent_tools import ToolContext, ToolExecutor, ToolRegistry
from app.director.business_flows import (
    BusinessFlowDefinitionRegistry,
    BusinessFlowService,
    FlowActionError,
)
from app.shared.db import resolve_business_flow_rls_scope, set_rls_context
from app.shared.errors import AppError

ACTION_DEADLINE_SECONDS = 60


class ToolFlowActionExecutor:
    """Executes flow actions through the fixed controlled tool allowlist."""

    def __init__(
        self,
        factory: Callable[[], AsyncSession],
        *,
        actor_id: UUID,
        workspace_id: UUID,
        project_id: UUID,
    ) -> None:
        # Flows may declare read-only model contract tools (capabilities/compile
        # preview); they never submit a Provider operation, so the registry
        # exposes them and the frozen definition still decides which are used.
        self._executor = ToolExecutor(factory, ToolRegistry(include_model_tools=True))
        self._actor_id = actor_id
        self._workspace_id = workspace_id
        self._project_id = project_id

    async def execute(
        self,
        *,
        action_key: str,
        arguments: Mapping[str, object],
        call_id: str,
        scope_type: str,
        scope_entity_id: UUID,
        attempt_id: UUID,
        thread_id: UUID | None,
    ) -> dict[str, object]:
        context = ToolContext(
            actor_id=self._actor_id,
            workspace_id=self._workspace_id,
            project_id=self._project_id,
            # A flow action has no Director Turn; the attempt is its audit identity
            # and the origin thread (when the plan came from a Turn) is preserved.
            turn_id=attempt_id,
            thread_id=thread_id or attempt_id,
            scope_type=scope_type,  # type: ignore[arg-type]
            scope_entity_id=scope_entity_id,
            expected_versions={},
            deadline=datetime.now(UTC) + timedelta(seconds=ACTION_DEADLINE_SECONDS),
        )
        try:
            result = await self._executor.execute(
                name=action_key,
                arguments=dict(arguments),
                call_id=call_id,
                context=context,
            )
        except AppError as exc:
            raise FlowActionError(exc.code or "FLOW_ACTION_FAILED") from exc
        except Exception as exc:  # noqa: BLE001 - a flow action never leaks internals
            raise FlowActionError("FLOW_ACTION_FAILED") from exc
        return result.model_dump(mode="json")


async def execute_business_flow(
    factory: Callable[[], AsyncSession],
    *,
    instance_id: UUID,
    settings: Settings | None = None,
    registry: BusinessFlowDefinitionRegistry | None = None,
) -> dict[str, object]:
    """Advance one flow instance as the single worker owner of its steps."""
    async with factory() as session:
        scope = await resolve_business_flow_rls_scope(session, instance_id=instance_id)
    if scope is None:
        return {"status": "missing", "instance_id": str(instance_id)}
    async with factory() as session:
        await set_rls_context(
            session,
            user_id=scope.user_id,
            workspace_id=scope.workspace_id,
            project_id=scope.project_id,
        )
        actor = await session.get(User, scope.user_id)
        project = await session.get(Project, scope.project_id)
        if actor is None or project is None:
            return {"status": "missing", "instance_id": str(instance_id)}
        service = BusinessFlowService(
            session, actor=actor, project=project, registry=registry
        )
        instance = await service.get(instance_id)
        if instance.status in {"succeeded", "failed", "cancelled"}:
            return {"status": instance.status, "instance_id": str(instance_id)}
        executor = ToolFlowActionExecutor(
            factory,
            actor_id=scope.user_id,
            workspace_id=scope.workspace_id,
            project_id=scope.project_id,
        )
        advanced = await service.advance(instance, executor=executor)
        await session.commit()
        return {
            "status": advanced.status,
            "instance_id": str(advanced.id),
            "revision": advanced.revision,
            "wait_reason": advanced.wait_reason,
        }


__all__ = ["ToolFlowActionExecutor", "execute_business_flow"]
