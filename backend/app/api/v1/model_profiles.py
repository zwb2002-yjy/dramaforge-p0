"""Model profile API (spec §34–§37, §96–§97).

Routes are workspace- or project-scoped per repo convention (mirrors
provider-connections / generations). The API never exposes credentials, base
URLs or raw wire payloads (spec §47/§97); ``model_id`` + option values only.

The route layer lives under ``app.api`` (not ``app.providers``) to keep the
providers layer free of HTTP imports (boundary test §68).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from app.access.projects import ProjectService
from app.api.deps import (
    CsrfDep,
    CurrentUser,
    SessionDep,
    require_selected_workspace,
)
from app.providers.model_profiles.models import (
    ModelSlotBinding,
    SimpleModeSelection,
)
from app.providers.model_profiles.orm import ProductionModelProfile
from app.providers.model_profiles.resolver import ModelBindingResolver
from app.providers.model_profiles.schemas import (
    BindingInput,
    EffectiveBindingRead,
    ModelSlotRead,
    ProfileCreate,
    ProfileRead,
    ProfileSummaryRead,
    ProfileUpdate,
    ProfileValidateRequest,
    ProfileValidateResponse,
    ProfileValidationIssue,
    SimpleModeApply,
)
from app.providers.model_profiles.service import ProductionModelProfileService
from app.providers.model_profiles.slots import (
    MODEL_SLOT_DEFINITIONS,
    P0_SLOTS,
    ModelSlot,
    slot_definition,
)

router = APIRouter(tags=["model-profiles"])


@router.get(
    "/model-slots",
    response_model=list[ModelSlotRead],
    dependencies=[Depends(require_selected_workspace)],
)
async def list_model_slots() -> list[ModelSlotRead]:
    return [
        ModelSlotRead(
            id=str(definition.slot),
            display_name=_slot_display_name(definition.slot),
            capabilities=[str(c) for c in definition.required_capabilities],
            description=definition.description,
            p0_scope=definition.slot in P0_SLOTS,
        )
        for definition in MODEL_SLOT_DEFINITIONS.values()
    ]


def _slot_display_name(slot: ModelSlot) -> str:
    return {
        ModelSlot.PLANNING_BRIEF: "策划 / Brief",
        ModelSlot.PLANNING_SCRIPT: "剧本",
        ModelSlot.PLANNING_STORYBOARD: "分镜规划",
        ModelSlot.VISUAL_CHARACTER: "角色图",
        ModelSlot.VISUAL_STORYBOARD: "分镜图",
        ModelSlot.VISUAL_KEYFRAME: "镜头关键帧",
        ModelSlot.VISUAL_IMAGE_EDIT: "图片编辑",
        ModelSlot.VIDEO_SHOT: "镜头视频",
        ModelSlot.AUDIO_TTS: "语音合成",
    }.get(slot, str(slot))


def _to_domain_bindings(
    raw: dict[str, BindingInput],
) -> dict[ModelSlot, ModelSlotBinding]:
    result: dict[ModelSlot, ModelSlotBinding] = {}
    for slot_value, item in raw.items():
        try:
            slot = ModelSlot(slot_value)
        except ValueError as exc:
            from app.providers.model_profiles.errors import profile_slot_unknown

            raise profile_slot_unknown(slot_value) from exc
        result[slot] = ModelSlotBinding(
            slot=slot,
            model_id=item.model_id,
            native_options=item.native_options,
            enabled=item.enabled,
        )
    return result


def _assert_workspace_profile(profile: ProductionModelProfile, workspace_id: UUID) -> None:
    if profile.workspace_id != workspace_id:
        from app.shared.errors import NotFoundError

        raise NotFoundError("model profile not found")


@router.get(
    "/workspaces/{workspace_id}/model-profiles",
    response_model=list[ProfileSummaryRead],
    dependencies=[Depends(require_selected_workspace)],
)
async def list_workspace_profiles(
    workspace_id: UUID,
    session: SessionDep,
) -> list[ProfileSummaryRead]:
    service = ProductionModelProfileService(session)
    profiles = await service.list_workspace_profiles(workspace_id=workspace_id)
    return [
        ProfileSummaryRead(
            id=profile.id,
            workspace_id=profile.workspace_id,
            project_id=profile.project_id,
            name=profile.name,
            version=profile.version,
            is_default=profile.is_default,
            binding_slots=sorted(str(slot) for slot in profile.bindings),
            updated_at=profile.updated_at,
        )
        for profile in profiles
    ]


@router.post(
    "/workspaces/{workspace_id}/model-profiles",
    response_model=ProfileRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_selected_workspace)],
)
async def create_workspace_profile(
    workspace_id: UUID,
    body: ProfileCreate,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> ProfileRead:
    service = ProductionModelProfileService(session)
    profile = await service.create(
        workspace_id=workspace_id,
        actor_id=user.id,
        name=body.name,
        bindings=_to_domain_bindings(body.bindings),
        is_default=body.is_default,
        copy_from=body.copy_from,
    )
    await session.commit()
    return await service.profile_read(profile)


@router.get(
    "/workspaces/{workspace_id}/model-profiles/{profile_id}",
    response_model=ProfileRead,
    dependencies=[Depends(require_selected_workspace)],
)
async def get_workspace_profile(
    workspace_id: UUID,
    profile_id: UUID,
    session: SessionDep,
) -> ProfileRead:
    service = ProductionModelProfileService(session)
    profile = await service.get(profile_id=profile_id)
    _assert_workspace_profile(profile, workspace_id)
    return await service.profile_read(profile)


@router.put(
    "/workspaces/{workspace_id}/model-profiles/{profile_id}",
    response_model=ProfileRead,
    dependencies=[Depends(require_selected_workspace)],
)
async def update_workspace_profile(
    workspace_id: UUID,
    profile_id: UUID,
    body: ProfileUpdate,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> ProfileRead:
    service = ProductionModelProfileService(session)
    profile = await service.get(profile_id=profile_id)
    _assert_workspace_profile(profile, workspace_id)
    bindings = (
        _to_domain_bindings(body.bindings) if body.bindings is not None else None
    )
    profile = await service.update(
        profile_id=profile_id,
        actor_id=user.id,
        name=body.name,
        bindings=bindings,
        is_default=body.is_default,
        expected_version=body.expected_version,
    )
    await session.commit()
    return await service.profile_read(profile)


@router.post(
    "/workspaces/{workspace_id}/model-profiles/{profile_id}/simple-mode",
    response_model=ProfileRead,
    dependencies=[Depends(require_selected_workspace)],
)
async def apply_simple_mode(
    workspace_id: UUID,
    profile_id: UUID,
    body: SimpleModeApply,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> ProfileRead:
    service = ProductionModelProfileService(session)
    profile = await service.get(profile_id=profile_id)
    _assert_workspace_profile(profile, workspace_id)
    profile = await service.apply_simple_mode(
        profile_id=profile_id,
        selection=SimpleModeSelection(
            llm_model_id=body.llm_model_id,
            image_model_id=body.image_model_id,
            video_model_id=body.video_model_id,
        ),
        actor_id=user.id,
        expected_version=body.expected_version,
    )
    await session.commit()
    return await service.profile_read(profile)


@router.delete(
    "/workspaces/{workspace_id}/model-profiles/{profile_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    dependencies=[Depends(require_selected_workspace)],
)
async def delete_workspace_profile(
    workspace_id: UUID,
    profile_id: UUID,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> Response:
    service = ProductionModelProfileService(session)
    profile = await service.get(profile_id=profile_id)
    _assert_workspace_profile(profile, workspace_id)
    await service.delete(profile_id=profile_id, actor_id=user.id)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/projects/{project_id}/model-profile",
    response_model=ProfileRead,
    dependencies=[Depends(require_selected_workspace)],
)
async def get_project_profile(
    project_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> ProfileRead:
    project = await ProjectService(session).get_project_for_owner(
        project_id=project_id, actor=user
    )
    service = ProductionModelProfileService(session)
    profile = await service.get_project_profile(project_id=project.id)
    if profile is None:
        from app.providers.model_profiles.errors import profile_not_found

        raise profile_not_found()
    return await service.profile_read(profile)


@router.put(
    "/projects/{project_id}/model-profile",
    response_model=ProfileRead,
    dependencies=[Depends(require_selected_workspace)],
)
async def put_project_profile(
    project_id: UUID,
    body: ProfileUpdate,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> ProfileRead:
    project = await ProjectService(session).get_project_for_owner(
        project_id=project_id, actor=user
    )
    service = ProductionModelProfileService(session)
    profile = await service.get_project_profile(project_id=project.id)
    if profile is None:
        # Snapshot the workspace default into a project profile on first write
        # (spec §54 Snapshot semantics — the project stops live-inheriting).
        workspace_default = await service.get_workspace_default(
            workspace_id=project.workspace_id
        )
        profile = await service.create(
            workspace_id=project.workspace_id,
            actor_id=user.id,
            name="项目模型方案",
            bindings={},
            project_id=project.id,
            copy_from=workspace_default.id if workspace_default is not None else None,
        )
    bindings = (
        _to_domain_bindings(body.bindings) if body.bindings is not None else None
    )
    profile = await service.update(
        profile_id=profile.id,
        actor_id=user.id,
        name=body.name,
        bindings=bindings,
        is_default=None if profile.project_id is not None else body.is_default,
        expected_version=body.expected_version,
    )
    await session.commit()
    return await service.profile_read(profile)


@router.post(
    "/model-profiles/validate",
    response_model=ProfileValidateResponse,
    dependencies=[Depends(require_selected_workspace)],
)
async def validate_profile(
    body: ProfileValidateRequest,
    session: SessionDep,
    _: CsrfDep,
) -> ProfileValidateResponse:
    service = ProductionModelProfileService(session)
    report = service.validate_bindings(_to_domain_bindings(body.bindings))
    return ProfileValidateResponse(
        valid=report.valid,
        issues=[
            ProfileValidationIssue(
                code=issue.code,
                slot=issue.slot,
                model_id=issue.model_id,
                message=issue.message,
            )
            for issue in report.issues
        ],
    )


@router.get(
    "/projects/{project_id}/model-bindings/effective",
    response_model=list[EffectiveBindingRead],
    dependencies=[Depends(require_selected_workspace)],
)
async def get_effective_bindings(
    project_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> list[EffectiveBindingRead]:
    """Preview the effective slot→model map for a project (spec §37). This is
    resolution preview only — it never calls a Provider."""
    project = await ProjectService(session).get_project_for_owner(
        project_id=project_id, actor=user
    )
    service = ProductionModelProfileService(session)
    profile = await service.get_effective_for_project(project=project)
    if profile is None:
        return []
    from app.providers.model_profiles.service import parse_bindings

    resolver = ModelBindingResolver(session, registry=service._registry)
    result: list[EffectiveBindingRead] = []
    for slot, binding in parse_bindings(profile.bindings).items():
        if not binding.enabled:
            continue
        first_capability = slot_definition(slot).required_capabilities[0]
        try:
            resolved = await resolver.resolve(
                workspace_id=project.workspace_id,
                project_id=project.id,
                slot=slot,
                capability=first_capability,
            )
        except Exception:
            # Preview only: a slot whose bound model cannot serve the first
            # capability (e.g. an i2v-only video model) is skipped, not 500.
            continue
        result.append(
            EffectiveBindingRead(
                slot=str(resolved.slot),
                capability=str(resolved.capability),
                model_id=resolved.model_id,
                source=resolved.source,
                profile_id=resolved.profile_id,
                profile_version=resolved.profile_version,
                native_options=resolved.native_options,
            )
        )
    return result
