"""Workflow planning freeze API (WF13).

Freezes the *user-selected* workflow template identity and the multi-character
participation plan onto existing ``Shot.director_state`` — no new persistence,
no Provider call, no second truth.  The capability assessment is deterministic
and fails closed: an unsupported multi-character shot can be frozen for
planning visibility but its UNSUPPORTED status is recorded, the read model
surfaces it, and every paid dispatch path re-validates references before any
Provider POST.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.access.models import Project
from app.access.projects import ProjectService
from app.api.deps import CsrfDep, CurrentUser, SessionDep, require_selected_workspace
from app.assets.models import Episode, Scene, Shot
from app.director.workflows.character_participation import (
    DialogueRole,
    ScreenRole,
    ShotCharacterParticipation,
    ShotParticipationPlan,
    participation_director_state,
)
from app.director.workflows.contracts import (
    TemplateResolveStatus,
    WorkflowTemplateRequest,
)
from app.director.workflows.library import get_default_registry
from app.director.workflows.reference_capability import (
    MultiCharacterCapabilityStatus,
    assess_multi_character_capability,
)
from app.director.workflows.resolver import WorkflowTemplateResolver
from app.director.workflows.workflow_read_models import (
    CapabilityAssessmentSummary,
    ParticipationEntry,
    build_shot_workflow_state,
)
from app.shared.errors import NotFoundError, ValidationAppError

router = APIRouter(
    tags=["workflow-planning"], dependencies=[Depends(require_selected_workspace)]
)


def _load_participations(director_state: dict[str, object]) -> list[ParticipationEntry]:
    raw = director_state.get("workflow_participations")
    entries: list[ParticipationEntry] = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                entries.append(ParticipationEntry.model_validate(item))
            except Exception:  # noqa: BLE001 - a malformed entry never breaks reads
                continue
    return entries


async def _shot_with_episode(
    session: SessionDep, *, project_id: UUID, shot_id: UUID, actor_user: CurrentUser
) -> tuple[Shot, UUID]:
    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=actor_user)
    row = (
        await session.execute(
            select(Shot, Episode)
            .join(Scene, Scene.id == Shot.scene_id)
            .join(Episode, Episode.id == Scene.episode_id)
            .where(Shot.id == shot_id, Shot.project_id == project_id)
        )
    ).first()
    if row is None:
        raise NotFoundError("shot not found")
    shot, episode = row
    return shot, episode.id


@router.get("/projects/{project_id}/shots/{shot_id}/workflow-state")
async def get_shot_workflow_state(
    project_id: UUID,
    shot_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> dict[str, object]:
    """Wire-visible workflow state for one shot (read-only aggregation).

    Resolves the workspace keyframe manifest so ``capability_assessment`` is a
    deterministic read (mirrors the planning freeze), letting the UI surface the
    EXACT / APPROXIMATE / UNSUPPORTED status honestly without a provider call.
    """
    from app.providers.manifest import ModelManifest
    from app.providers.workspace_router import resolve_workspace_bridge

    shot, episode_id = await _shot_with_episode(
        session, project_id=project_id, shot_id=shot_id, actor_user=user
    )
    project = await session.get(Project, project_id)
    assert project is not None
    assessment_manifest: ModelManifest | None = None
    try:
        bridge = await resolve_workspace_bridge(
            session,
            workspace_id=project.workspace_id,
            provider_type="agnes",
            media_kind="image",
        )
        if isinstance(bridge.manifest, ModelManifest):
            assessment_manifest = bridge.manifest
    except Exception:  # noqa: BLE001 - a read model must never fail a page
        assessment_manifest = None
    state = build_shot_workflow_state(
        shot=shot,
        episode_id=episode_id,
        assessment_manifest=assessment_manifest,
    )
    return {"workflow_state": state.model_dump(mode="json")}


class FreezeWorkflowBody(BaseModel):
    """Freeze an explicitly chosen template identity (never auto-picked)."""

    expected_version: int = Field(ge=1)
    template_key: str = Field(min_length=1, max_length=120)


class ParticipationItemBody(BaseModel):
    asset_id: UUID
    asset_version_id: UUID | None = None
    screen_role: str = "secondary"
    importance: int = Field(default=50, ge=0, le=100)
    wardrobe_asset_version_id: UUID | None = None
    position: str = ""
    pose: str = ""
    gaze_target: str = ""
    action: str = ""
    expression: str = ""
    dialogue_role: str = "none"


class FreezeParticipationBody(BaseModel):
    expected_version: int = Field(ge=1)
    participations: list[ParticipationItemBody] = Field(max_length=8)


class WorkflowStateResponse(BaseModel):
    workflow_state: dict[str, object]


def _require_resolved_or_raise(resolution_status: TemplateResolveStatus, reason: str | None,
                               template_key: str) -> None:
    if resolution_status is not TemplateResolveStatus.RESOLVED:
        raise ValidationAppError(
            "requested workflow template is unavailable",
            details={
                "code": "TEMPLATE_UNAVAILABLE",
                "reason": reason,
                "template_key": template_key,
            },
        )


@router.post(
    "/projects/{project_id}/shots/{shot_id}/workflow-template",
    response_model=WorkflowStateResponse,
)
async def freeze_workflow_template(
    project_id: UUID,
    shot_id: UUID,
    body: FreezeWorkflowBody,
    user: CurrentUser,
    session: SessionDep,
    _csrf: CsrfDep,
) -> WorkflowStateResponse:
    """Freeze an explicitly requested workflow template onto the shot.

    The request must resolve to a registered, eligible template for the shot's
    current visible character count; anything else raises UNAVAILABLE and
    nothing is frozen (fail closed).
    """
    shot, episode_id = await _shot_with_episode(
        session, project_id=project_id, shot_id=shot_id, actor_user=user
    )
    if shot.version != body.expected_version:
        raise ValidationAppError(
            "shot version conflict",
            details={"expected": body.expected_version, "actual": shot.version},
        )
    registry = get_default_registry()
    resolver = WorkflowTemplateResolver(registry)
    state = dict(shot.director_state or {})
    entries = _load_participations(state)
    visible_count = max(sum(1 for e in entries if e.screen_role != "offscreen"), 1)
    spec = registry.get(body.template_key)
    if spec is None:
        raise ValidationAppError(
            "requested workflow template is unavailable",
            details={
                "code": "TEMPLATE_UNAVAILABLE",
                "reason": f"template {body.template_key!r} is not registered",
                "template_key": body.template_key,
            },
        )
    # Explicit freeze: declare the template's own evidence so eligibility checks
    # intent/reference identity; character-count eligibility stays authoritative
    # (a 2-character template for a 1-visible-character shot is still UNAVAILABLE).
    resolution = resolver.resolve(
        WorkflowTemplateRequest(
            intent_tags=list(spec.intent_tags),
            medium="video",
            character_count=visible_count,
            reference_roles_present=list(spec.required_reference_roles),
            explicit_template_key=body.template_key,
        )
    )
    _require_resolved_or_raise(resolution.status, resolution.reason, body.template_key)
    spec = registry.get(body.template_key)
    assert spec is not None  # the resolver just resolved it from this registry
    shot.director_state = {
        **state,
        "workflow_template_key": spec.template_key,
        "workflow_template_version": spec.template_version,
        "workflow_template_contract_hash": spec.contract_hash,
        "quality_policy_id": spec.quality_policy_id,
        "repair_policy_id": spec.repair_policy_id,
    }
    shot.version += 1
    await session.flush()
    await session.commit()
    refreshed = build_shot_workflow_state(shot=shot, episode_id=episode_id)
    return WorkflowStateResponse(workflow_state=refreshed.model_dump(mode="json"))


@router.post(
    "/projects/{project_id}/shots/{shot_id}/participation-plan",
    response_model=WorkflowStateResponse,
)
async def freeze_participation_plan(
    project_id: UUID,
    shot_id: UUID,
    body: FreezeParticipationBody,
    user: CurrentUser,
    session: SessionDep,
    _csrf: CsrfDep,
) -> WorkflowStateResponse:
    """Freeze the multi-character participation plan onto ``Shot.director_state``.

    Validates cross-project bindings through the existing WF5 service.  The
    multi-subject capability assessment against the workspace keyframe model is
    recomputed here for planning visibility only: freezing itself is not gated
    (planning may proceed while UNSUPPORTED), but the assessment result is part
    of the response and every paid dispatch path independently fails closed
    before any Provider POST.
    """
    from app.director.workflows.participation_service import validate_participation_bindings
    from app.providers.capabilities import Capability
    from app.providers.manifest import ModelManifest
    from app.providers.workspace_router import resolve_workspace_bridge

    shot, episode_id = await _shot_with_episode(
        session, project_id=project_id, shot_id=shot_id, actor_user=user
    )
    if shot.version != body.expected_version:
        raise ValidationAppError(
            "shot version conflict",
            details={"expected": body.expected_version, "actual": shot.version},
        )
    project = await session.get(Project, project_id)
    assert project is not None

    roles: list[ShotCharacterParticipation] = []
    for item in body.participations:
        try:
            screen_role = ScreenRole(item.screen_role)
            dialogue_role = DialogueRole(item.dialogue_role)
        except ValueError as exc:
            raise ValidationAppError(f"invalid role value: {exc}") from exc
        roles.append(
            ShotCharacterParticipation(
                asset_id=item.asset_id,
                asset_version_id=item.asset_version_id,
                screen_role=screen_role,
                importance=item.importance,
                wardrobe_asset_version_id=item.wardrobe_asset_version_id,
                position=item.position[:80],
                pose=item.pose[:80],
                gaze_target=item.gaze_target[:120],
                action=item.action[:200],
                expression=item.expression[:80],
                dialogue_role=dialogue_role,
            )
        )
    plan = ShotParticipationPlan(participations=roles)
    # Cross-workspace / cross-project binding validation (WF5); raises on any
    # reference outside this project.
    await validate_participation_bindings(session, project_id=project_id, plan=plan)

    shot.director_state = {
        **dict(shot.director_state or {}),
        **participation_director_state(plan),
    }
    shot.version += 1
    await session.flush()
    await session.commit()

    # Planning-time capability visibility against the workspace keyframe model.
    assessment_summary: CapabilityAssessmentSummary | None = None
    try:
        bridge = await resolve_workspace_bridge(
            session,
            workspace_id=project.workspace_id,
            provider_type="agnes",
            media_kind="image",
        )
        manifest = bridge.manifest
        if isinstance(manifest, ModelManifest):
            result = assess_multi_character_capability(
                manifest=manifest,
                capability=Capability.IMAGE_GENERATE,
                mode_id=None,
                plan=plan,
            )
            assessment_summary = CapabilityAssessmentSummary(
                status=result.status.value,
                required_subject_references=result.required_subject_references,
                max_subject_references=result.max_subject_references,
                reason=result.reason,
                approximate_strategy_id=result.approximate_strategy_id,
            )
    except Exception:  # noqa: BLE001 - planning must not fail when no provider configured
        assessment_summary = None

    refreshed = build_shot_workflow_state(shot=shot, episode_id=episode_id)
    payload = dict(refreshed.model_dump(mode="json"))
    if assessment_summary is not None:
        payload["capability_assessment"] = assessment_summary.model_dump(mode="json")
    if (
        assessment_summary is not None
        and assessment_summary.status == MultiCharacterCapabilityStatus.UNSUPPORTED.value
    ):
        payload["paid_dispatch"] = {
            "allowed": False,
            "reason": "UNSUPPORTED multi-subject requirement; Provider POST blocked",
        }
    return WorkflowStateResponse(workflow_state=payload)
