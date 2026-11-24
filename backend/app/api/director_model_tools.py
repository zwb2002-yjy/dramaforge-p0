"""Compose authorized media diagnostics for Agent tools without execution ports."""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import User
from app.assets.agent_read_service import AgentReadService
from app.contracts.director_model_tools import (
    ModelCapabilitiesInput,
    ModelCapabilitiesRead,
    ModelCompilePreviewInput,
    ModelCompilePreviewRead,
    ModelToolScope,
)
from app.production.model_inspection import ModelInspectionService, ModelQueryRead
from app.production.workbench_execution import WorkbenchExecutionInput
from app.providers.catalog_loader import hash_manifest
from app.providers.connection_service import ProviderConnectionService
from app.shared.errors import ConflictError, NotFoundError, ValidationAppError


def _stale() -> ConflictError:
    return ConflictError(
        "Model, binding or observed version changed; inspect current facts again.",
        details={"code": "CONTEXT_STALE"},
    )


class ApiDirectorModelTools:
    """Own one read session; expose neither its session nor a production writer."""

    def __init__(self, factory: Callable[[], AsyncSession]) -> None:
        self._factory = factory

    async def _scope(
        self,
        session: AsyncSession,
        scope: ModelToolScope,
        request: ModelCompilePreviewInput | None = None,
    ) -> tuple[User, dict[str, int]]:
        reader = AgentReadService(
            session,
            actor_id=scope.actor_id,
            workspace_id=scope.workspace_id,
            project_id=scope.project_id,
        )
        project = await reader.project()
        observed = {f"project:{project.id}": project.version}
        if scope.scope_type in {"project", "story"}:
            if scope.scope_entity_id != scope.project_id:
                raise ValidationAppError(
                    "Project scope mismatch", details={"code": "ToolPermissionDenied"}
                )
        elif scope.scope_type == "scene":
            scene = await reader.scene(scope.scope_entity_id)
            observed[f"scene:{scene.id}"] = scene.version
        else:
            shot = await reader.shot(scope.scope_entity_id)
            observed[f"shot:{shot.id}"] = shot.version
        if request is not None:
            shot = await reader.shot(request.shot_id)
            if (
                scope.scope_type == "scene"
                and shot.scene_id != scope.scope_entity_id
                or scope.scope_type == "shot"
                and shot.id != scope.scope_entity_id
            ):
                raise ValidationAppError(
                    "Shot outside Director scope", details={"code": "ToolPermissionDenied"}
                )
            if shot.version != request.expected_shot_version:
                raise _stale()
            observed[f"shot:{shot.id}"] = shot.version
        for key, actual in observed.items():
            if key in scope.expected_versions and scope.expected_versions[key] != actual:
                raise _stale()
        actor = await session.get(User, scope.actor_id)
        if actor is None:
            raise NotFoundError("actor not found")
        return actor, observed

    @staticmethod
    async def _identity(
        session: AsyncSession,
        scope: ModelToolScope,
        result: ModelQueryRead,
    ) -> dict[str, object]:
        resolution = result.resolution
        if (
            resolution is None
            or result.binding_id is None
            or result.identity_hash is None
            or resolution.provider_connection_id is None
            or resolution.manifest_hash != result.report.manifest_hash
        ):
            raise ValidationAppError("current media binding has no exact inspection identity")
        connections = ProviderConnectionService(session)
        connection = await connections.get_connection(
            workspace_id=scope.workspace_id,
            connection_id=resolution.provider_connection_id,
        )
        revision = await connections.current_connection_revision(connection=connection)
        if (
            revision.base_url != connection.base_url
            or revision.provider_type != connection.provider_type
            or revision.protocol_profile != connection.protocol_profile
            or revision.credential_revision_id != connection.credential_id
        ):
            raise _stale()
        return {
            "binding_id": result.binding_id,
            "connection_revision_id": revision.id,
            "model_id": result.report.model_id,
            "model_revision": result.report.model_revision,
            "manifest_hash": result.report.manifest_hash,
            "identity_hash": hash_manifest(
                {
                    "inspection_identity_hash": result.identity_hash,
                    "connection_revision_id": str(revision.id),
                }
            ),
        }

    async def inspect(
        self,
        *,
        scope: ModelToolScope,
        request: ModelCapabilitiesInput,
    ) -> ModelCapabilitiesRead:
        async with self._factory() as session:
            actor, observed = await self._scope(session, scope)
            with session.no_autoflush:
                # Only the media stage path is permitted. Generic model/text
                # registry construction may resolve credentials, so it is not
                # exposed by this read-only port.
                result = await ModelInspectionService(session, actor=actor).get_model_capabilities(
                    project_id=scope.project_id,
                    stage=request.stage,
                    mode_id=request.mode_id,
                )
            identity = await self._identity(session, scope, result)
            assert result.resolution is not None
            return ModelCapabilitiesRead.model_validate(
                {
                    **identity,
                    "stage": request.stage,
                    "mode_id": request.mode_id,
                    "binding_status": result.resolution.status,
                    "binding_reason": result.resolution.reason,
                    "capabilities": {
                        key: value.model_dump(mode="json")
                        for key, value in result.report.capabilities.items()
                    },
                    "controls": result.report.controls,
                    "generation_options": {
                        key: value.model_dump(mode="json")
                        for key, value in result.generation_options.items()
                        if not value.parameter.sensitive
                    },
                    "limitations": result.report.limitations,
                    "observed_versions": observed,
                    "provenance": {"source": "ModelInspectionService", "kind": "media_contract"},
                }
            )

    async def preview(
        self,
        *,
        scope: ModelToolScope,
        request: ModelCompilePreviewInput,
    ) -> ModelCompilePreviewRead:
        async with self._factory() as session:
            actor, observed = await self._scope(session, scope, request)
            service = ModelInspectionService(session, actor=actor)
            with session.no_autoflush:
                before = await service.get_model_capabilities(
                    project_id=scope.project_id,
                    stage=request.stage,
                    mode_id=request.mode_id,
                )
                identity = await self._identity(session, scope, before)
                if (
                    before.binding_id != request.requested_binding_id
                    or identity["identity_hash"] != request.expected_identity_hash
                    or before.report.manifest_hash != request.expected_manifest_hash
                ):
                    raise _stale()
                result = await service.preview_generation_compile(
                    project_id=scope.project_id,
                    request=WorkbenchExecutionInput(
                        project_id=scope.project_id,
                        shot_id=request.shot_id,
                        stage=request.stage,
                        mode_id=request.mode_id,
                        prompt=request.prompt,
                        expected_shot_version=request.expected_shot_version,
                        requested_binding_id=request.requested_binding_id,
                        semantic_intent=request.semantic_intent,
                        references=request.references,
                        accept_approximations=False,
                    ),
                )
                after = await service.get_model_capabilities(
                    project_id=scope.project_id,
                    stage=request.stage,
                    mode_id=request.mode_id,
                )
                if await self._identity(session, scope, after) != identity:
                    raise _stale()
            if result.model.manifest_hash != request.expected_manifest_hash:
                raise _stale()
            compilation = result.compilation
            return ModelCompilePreviewRead.model_validate(
                {
                    **identity,
                    "stage": request.stage,
                    "mode_id": request.mode_id,
                    "plan_fingerprint": result.plan_fingerprint,
                    "snapshot_hash": result.snapshot_hash,
                    "prompt_hash": compilation.prompt_hash,
                    "semantic_hash": compilation.semantic_hash,
                    "wire_fingerprint": compilation.wire_fingerprint,
                    "readiness": compilation.readiness,
                    "requested_options": compilation.requested_options,
                    "effective_options": compilation.effective_options,
                    "references": [ref.model_dump(mode="json") for ref in result.reference_plan],
                    "errors": compilation.errors,
                    "warnings": [*result.warnings, *compilation.warnings],
                    "observed_versions": observed,
                    "provenance": {"source": "ModelInspectionService", "kind": "compiler_preview"},
                }
            )
