"""Wire-visible workflow read models (WF13).

Aggregates the *existing* execution truth (Shot.director_state / Scene.design_state /
NodeRun.input_snapshot / formal artifacts) into typed read models for the API and
the Professional workbench UI.  Pure reads: no persistence is created here and no
Provider request can ever originate from this module.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.assets.models import Episode, Scene, Shot
from app.director.workflows.contracts import (
    TemplateResolveSource,
    TemplateResolveStatus,
    WorkflowTemplateResolution,
    WorkflowTemplateSpec,
)
from app.director.workflows.library import get_default_registry
from app.director.workflows.reference_capability import (
    REGISTERED_STAGED_STRATEGIES,
    assess_multi_character_capability,
)
from app.director.workflows.registry import WorkflowTemplateRegistry
from app.director.workflows.scene_orchestration import (
    SceneProductionState,
    SceneProductionStatus,
    scene_production_status,
)
from app.providers.manifest import ModelManifest


class ParticipationEntry(BaseModel):
    """One character's frozen participation, as stored in ``director_state``."""

    # The stored payload carries ``identity_reference_ids`` which this summary
    # view intentionally omits; allow (and ignore) it here.
    model_config = ConfigDict(frozen=True, extra="ignore")

    asset_id: str
    asset_version_id: str | None = None
    screen_role: str
    importance: int = 50
    wardrobe_asset_version_id: str | None = None
    position: str = ""
    pose: str = ""
    gaze_target: str = ""
    action: str = ""
    expression: str = ""
    dialogue_role: str = "none"


class CapabilityAssessmentSummary(BaseModel):
    """Assessed multi-subject capability of the keyframe model for a shot."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: str
    required_subject_references: int
    max_subject_references: int
    reason: str
    approximate_strategy_id: str | None = None


class ShotWorkflowState(BaseModel):
    """Wire-visible workflow state for one shot (planning + frozen identity)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    shot_id: UUID
    scene_id: UUID
    episode_id: UUID
    shot_number: int
    status: str
    workflow_template_key: str | None
    template_version: str | None
    template_contract_hash: str | None
    template_resolution_status: str
    quality_policy_id: str | None
    repair_policy_id: str | None
    required_reference_roles: list[str] = Field(default_factory=list)
    supported_character_count: list[int] = Field(default_factory=list)
    intent_tags: list[str] = Field(default_factory=list)
    participations: list[ParticipationEntry] = Field(default_factory=list)
    capability_assessment: CapabilityAssessmentSummary | None = None

    @property
    def has_frozen_template(self) -> bool:
        return self.workflow_template_key is not None


def _load_participations(director_state: dict[str, object]) -> list[ParticipationEntry]:
    raw = director_state.get("workflow_participations")
    entries: list[ParticipationEntry] = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                entries.append(ParticipationEntry.model_validate(item))
            except Exception:  # noqa: BLE001 - read model must never fail a page
                continue
    return entries


def _resolve_template(
    *,
    template_key: str | None,
    registry: WorkflowTemplateRegistry | None,
) -> tuple[WorkflowTemplateResolution | None, WorkflowTemplateSpec | None]:
    """Report whether the frozen identity is still reproducible from code.

    Read-layer semantics follow G-WF-03 (retry/resume uses the frozen
    identity): ``RESOLVED`` means the frozen key is registered with a live
    spec (version + contract hash available); ``UNAVAILABLE`` means the frozen
    key no longer exists in the registry.  Per-request *eligibility* (intent /
    reference / character-count) stays a freeze-time and dispatch-time check;
    this module never silently substitutes another template (G-WF-04).
    """
    spec: WorkflowTemplateSpec | None = None
    resolution: WorkflowTemplateResolution | None = None
    reg = registry or get_default_registry()
    if template_key:
        spec = reg.get(template_key)
        if spec is not None:
            resolution = WorkflowTemplateResolution(
                requested_template_key=template_key,
                resolved_template_key=spec.template_key,
                template_version=spec.template_version,
                status=TemplateResolveStatus.RESOLVED,
                source=TemplateResolveSource.EXPLICIT,
                reason=None,
            )
        else:
            resolution = WorkflowTemplateResolution(
                requested_template_key=template_key,
                resolved_template_key=None,
                template_version=None,
                status=TemplateResolveStatus.UNAVAILABLE,
                source=TemplateResolveSource.EXPLICIT,
                reason=f"frozen template {template_key!r} is not registered",
            )
    return resolution, spec


def build_shot_workflow_state(
    *,
    shot: Shot,
    episode_id: UUID,
    assessment_manifest: ModelManifest | None = None,
    registry: WorkflowTemplateRegistry | None = None,
) -> ShotWorkflowState:
    """Build the wire-visible workflow state for one shot.

    ``assessment_manifest`` is an optional V3 ``ModelManifest`` of the resolved
    keyframe model; when present (and the shot has a participation plan) the
    multi-subject capability assessment is recomputed deterministically.
    """
    state = dict(shot.director_state or {})
    template_key_raw = state.get("workflow_template_key")
    template_key = (
        str(template_key_raw)
        if isinstance(template_key_raw, str) and template_key_raw
        else None
    )
    participations = _load_participations(state)
    visible_count = sum(
        1 for item in participations if item.screen_role != "offscreen"
    )

    resolution, spec = _resolve_template(template_key=template_key, registry=registry)

    assessment: CapabilityAssessmentSummary | None = None
    if assessment_manifest is not None and visible_count > 0:
        from app.director.workflows.character_participation import (
            ScreenRole,
            ShotCharacterParticipation,
            ShotParticipationPlan,
        )

        plan = ShotParticipationPlan(
            participations=[
                ShotCharacterParticipation(
                    asset_id=UUID(entry.asset_id),
                    asset_version_id=(
                        UUID(entry.asset_version_id) if entry.asset_version_id else None
                    ),
                    screen_role=ScreenRole(entry.screen_role),
                    importance=entry.importance,
                    wardrobe_asset_version_id=(
                        UUID(entry.wardrobe_asset_version_id)
                        if entry.wardrobe_asset_version_id
                        else None
                    ),
                )
                for entry in participations
            ]
        )
        from app.providers.capabilities import Capability

        result = assess_multi_character_capability(
            manifest=assessment_manifest,
            capability=Capability.IMAGE_GENERATE,
            mode_id=None,
            plan=plan,
        )
        assessment = CapabilityAssessmentSummary(
            status=result.status.value,
            required_subject_references=result.required_subject_references,
            max_subject_references=result.max_subject_references,
            reason=result.reason,
            approximate_strategy_id=result.approximate_strategy_id,
        )

    return ShotWorkflowState(
        shot_id=shot.id,
        scene_id=shot.scene_id,
        episode_id=episode_id,
        shot_number=shot.shot_number,
        status=str(shot.status),
        workflow_template_key=(
            template_key if resolution is not None and template_key else template_key
        ),
        template_version=(spec.template_version if spec is not None else None),
        template_contract_hash=(spec.contract_hash if spec is not None else None),
        template_resolution_status=(
            resolution.status.value if resolution is not None else "NONE"
        ),
        quality_policy_id=(spec.quality_policy_id if spec is not None else None),
        repair_policy_id=(spec.repair_policy_id if spec is not None else None),
        required_reference_roles=(
            list(spec.required_reference_roles) if spec is not None else []
        ),
        supported_character_count=(
            list(spec.supported_character_count) if spec is not None else []
        ),
        intent_tags=(list(spec.intent_tags) if spec is not None else []),
        participations=participations,
        capability_assessment=assessment,
    )


class SceneWorkflowView(BaseModel):
    """Scene-level view: production status + per-shot workflow states."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scene_id: UUID
    episode_id: UUID
    episode_number: int
    scene_number: int
    location_name: str
    time_of_day: str
    synopsis: str
    production_status: SceneProductionStatus
    shots: list[ShotWorkflowState] = Field(default_factory=list)


class WorkflowOverview(BaseModel):
    """Project-wide wire-visible workflow overview (episodes → scenes → shots)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_id: UUID
    episodes: list[dict[str, object]] = Field(default_factory=list)
    scenes: list[SceneWorkflowView] = Field(default_factory=list)
    total_shots: int = 0
    formal_shots: int = 0
    blocked_scenes: int = 0
    review_required_scenes: int = 0
    unsupported_capability_shots: int = 0
    available_staged_strategies: list[str] = Field(
        default_factory=lambda: sorted(REGISTERED_STAGED_STRATEGIES)
    )


def build_project_workflow_overview(
    *,
    project_id: UUID,
    scenes: list[tuple[Episode, Scene]],
    shots_by_scene: dict[UUID, list[Shot]],
    manifests_by_scene: dict[UUID, ModelManifest] | None = None,
    registry: WorkflowTemplateRegistry | None = None,
) -> WorkflowOverview:
    """Aggregate episode → scene → shot workflow views (pure read)."""
    views: list[SceneWorkflowView] = []
    # episode.id -> [scene_count, total_shots]; insertion order follows episode order.
    episode_counts: dict[UUID, list[int]] = {}
    # episode.id -> first-seen metadata, so ordering stays deterministic.
    episode_meta: dict[UUID, dict[str, object]] = {}
    total = formal = blocked_scenes = review_scenes = unsupported_shots = 0

    reg = registry or get_default_registry()
    for episode, scene in sorted(
        scenes, key=lambda pair: (pair[0].episode_number, pair[1].scene_number)
    ):
        shots = sorted(shots_by_scene.get(scene.id, []), key=lambda s: s.shot_number)
        status = scene_production_status(scene, shots)
        manifest = (manifests_by_scene or {}).get(scene.id)
        shot_states = [
            build_shot_workflow_state(
                shot=shot,
                episode_id=episode.id,
                assessment_manifest=manifest,
                registry=reg,
            )
            for shot in shots
        ]
        views.append(
            SceneWorkflowView(
                scene_id=scene.id,
                episode_id=episode.id,
                episode_number=episode.episode_number,
                scene_number=scene.scene_number,
                location_name=scene.location_name,
                time_of_day=scene.time_of_day,
                synopsis=scene.synopsis,
                production_status=status,
                shots=shot_states,
            )
        )
        counts = episode_counts.setdefault(episode.id, [0, 0])
        counts[0] += 1
        counts[1] += len(shots)
        episode_meta.setdefault(
            episode.id,
            {
                "episode_id": episode.id,
                "episode_number": episode.episode_number,
                "title": episode.title,
                "synopsis": episode.synopsis,
            },
        )

        total += len(shots)
        formal += status.formal_shots
        if status.state is SceneProductionState.BLOCKED:
            blocked_scenes += 1
        elif status.state is SceneProductionState.REVIEW:
            review_scenes += 1
        unsupported_shots += sum(
            1
            for item in shot_states
            if item.capability_assessment is not None
            and item.capability_assessment.status == "UNSUPPORTED"
        )

    episodes: list[dict[str, object]] = []
    for episode_id, meta in episode_meta.items():
        counts = episode_counts[episode_id]
        episodes.append(
            {
                **meta,
                "scene_count": counts[0],
                "total_shots": counts[1],
            }
        )

    return WorkflowOverview(
        project_id=project_id,
        episodes=episodes,
        scenes=views,
        total_shots=total,
        formal_shots=formal,
        blocked_scenes=blocked_scenes,
        review_required_scenes=review_scenes,
        unsupported_capability_shots=unsupported_shots,
    )
