"""P4-05 WorkbenchExecutionService (07 §16 / 03 §35).

Orchestrates one Professional shot execution without any legacy gate:

- Build Plan  (ExecutionModelResolver + P4-02 reference compiler + P4-01 plan)
- Freeze inputs (deterministic plan fingerprint)
- Resolve graph (GraphService, scope_type=shot)
- Create NodeRun (status=queued, worker picks it up)
- Persist snapshot (plan + identity, never secrets)
- Dispatch worker (queued NodeRun -> Worker)

Forbidden here: direct Provider HTTP, automatic model fallback, or Agent
approval. The resolved model identity is frozen into the Workbench plan.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Final, Literal, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project
from app.assets.models import Asset, AssetVersion, AssetVersionReference, Episode, Scene, Shot
from app.config import get_settings
from app.execution.models import Artifact, GraphEdge, GraphNode, NodeRun
from app.execution.shot_pipeline import (
    SHOT_PIPELINE_TEMPLATE_KEY,
    shot_pipeline_definition,
)
from app.production.execution_plan import (
    WorkbenchExecutionPlan,
)
from app.production.formal_selection import require_formal_keyframe
from app.production.models import GraphVersion, ProductionGraph, ShotReferenceBinding
from app.production.reference_intents import (
    ShotReferenceIntent,
    compile_references,
)
from app.production.service import GraphService
from app.providers.capabilities import Capability
from app.providers.catalog_models import ModelCatalogEntry
from app.providers.manifest import ModelCapabilityManifest, to_v3_model_manifest
from app.providers.model_profiles.slots import ModelSlot
from app.providers.model_resolution import ExecutionModelResolver
from app.providers.models import ProviderConnection, ProviderConnectionRevision
from app.shared.enums import GraphStatus
from app.shared.errors import ConflictError, ValidationAppError

PlanStage = Literal["image_keyframe", "video"]

_STAGE_CONTRACT: Final[dict[PlanStage, tuple[ModelSlot, Capability, str, str]]] = {
    "image_keyframe": (
        ModelSlot.VISUAL_KEYFRAME,
        Capability.IMAGE_GENERATE,
        "keyframe",
        "keyframe",
    ),
    "video": (
        ModelSlot.VIDEO_SHOT,
        Capability.VIDEO_IMAGE_TO_VIDEO,
        "video",
        "video",
    ),
}

_PURE_UPSTREAM_NODE_TYPES = frozenset({"prompt", "prompt_compose"})
_NODE_RUN_IDEMPOTENCY_MAX_LENGTH: Final[int] = 160


def workbench_request_hash(payload: Mapping[str, object]) -> str:
    """Fingerprint the validated command body, before mutable model resolution."""
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _workbench_idempotency_key(
    *,
    stage: PlanStage,
    override: str | None,
    plan_fingerprint: str,
) -> str:
    """Keep caller idempotency deterministic while respecting the DB contract."""
    raw = f"workbench:{stage}:{override}" if override else f"workbench:{stage}:{plan_fingerprint}"
    if len(raw) <= _NODE_RUN_IDEMPOTENCY_MAX_LENGTH:
        return raw
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"workbench:{stage}:sha256:{digest}"


def _chain_input_hash(payload: dict[str, object]) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def _ensure_pure_chain_upstreams(
    session: AsyncSession,
    *,
    project_id: UUID,
    graph_version_id: UUID,
    target_node_id: UUID,
    shot_id: UUID,
    prompt: str,
    stage: PlanStage,
    created_by: UUID,
) -> None:
    """Create missing queued pure upstream runs for the shot pipeline.

    The Workbench API dispatches one concrete media NodeRun (keyframe/video).
    The frozen shot graph still requires its pure ``prompt`` upstream to have
    a durable run before a media run may execute.  These zero-provider runs
    are created here as queued facts and then picked up by the same
    dispatcher/worker path; the media run waits/retries until they complete.
    """
    edges = (
        (
            await session.execute(
                select(GraphEdge, GraphNode)
                .join(GraphNode, GraphNode.id == GraphEdge.upstream_node_id)
                .where(GraphEdge.graph_version_id == graph_version_id)
                .where(GraphEdge.downstream_node_id == target_node_id)
                .where(GraphEdge.required.is_(True))
                .order_by(GraphEdge.input_port, GraphEdge.position)
            )
        )
        .tuples()
        .all()
    )
    source_commit = get_settings().source_commit.strip() or "development"
    for _edge, node in edges:
        if node.node_type not in _PURE_UPSTREAM_NODE_TYPES:
            continue
        existing = list(
            (
                await session.execute(
                    select(NodeRun)
                    .where(NodeRun.project_id == project_id)
                    .where(NodeRun.graph_version_id == graph_version_id)
                    .where(NodeRun.graph_node_id == node.id)
                    .order_by(NodeRun.attempt_no.desc(), NodeRun.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        latest = existing[0] if existing else None
        if latest is not None and latest.status in {
            "queued",
            "running",
            "completed",
            "cached",
            "completed_after_cancel",
        }:
            continue
        attempt_no = (max((row.attempt_no or 0) for row in existing) + 1) if existing else 1
        payload: dict[str, object] = {
            "plan": {"prompt": prompt},
            "prompt": prompt,
            "project_id": str(project_id),
            "shot_id": str(shot_id),
            "node_key": node.node_key,
            "stage": stage,
            "source_commit": source_commit,
            "professional_unified": True,
            "execution_path": "unified-v1",
        }
        session.add(
            NodeRun(
                project_id=project_id,
                graph_version_id=graph_version_id,
                graph_node_id=node.id,
                attempt_no=attempt_no,
                idempotency_key=(f"workbench:chain:{stage}:{node.node_key}:{shot_id}:{attempt_no}"),
                input_hash=_chain_input_hash(payload),
                status="queued",
                input_snapshot=payload,
                created_by=created_by,
            )
        )
        await session.flush()


class WorkbenchExecutionError(ValidationAppError):
    """Raised when a workbench plan cannot be built or dispatched."""


class WorkbenchExecutionInput(BaseModel):
    """Inputs for one shot execution (image keyframe or video)."""

    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    shot_id: UUID
    shot_experiment_id: UUID | None = None
    stage: PlanStage
    prompt: str = Field(min_length=1)
    semantic_intent: dict[str, JsonValue] = Field(default_factory=dict)
    mode_id: str = Field(min_length=1, max_length=120)
    requested_model_id: str | None = None
    requested_binding_id: UUID | None = None
    accept_approximations: bool = False
    references: list[ShotReferenceIntent] = Field(default_factory=list)
    expected_shot_version: int | None = None


def _node_run_input_hash(snapshot: dict[str, object]) -> str:
    canonical = json.dumps(
        snapshot,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _deep_merge(left: Mapping[str, object], right: Mapping[str, object]) -> dict[str, object]:
    merged = dict(left)
    for key, value in right.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            merged[key] = _deep_merge(
                cast(Mapping[str, object], merged[key]),
                value,
            )
        else:
            merged[key] = value
    return merged


def _skill_guidance(*snapshots: Mapping[str, object]) -> list[dict[str, object]]:
    ordered: dict[str, dict[str, object]] = {}
    for snapshot in snapshots:
        raw = snapshot.get("skill_guidance")
        if not isinstance(raw, list):
            continue
        for item in raw:
            if not isinstance(item, Mapping):
                continue
            key = str(item.get("skill_key") or "")
            if key:
                ordered[key] = dict(item)
    return list(ordered.values())


def _compose_effective_prompt(
    *,
    base_prompt: str,
    effective_intent: Mapping[str, object],
    skill_guidance: list[dict[str, object]],
    shot_language: Mapping[str, object],
    continuity_context: Mapping[str, object],
) -> str:
    guidance = {
        "priority": ("saved user values > accepted proposal > project override > pack default"),
        "effective_intent": dict(effective_intent),
        "skills": [
            {
                "skill_key": row.get("skill_key"),
                "skill_version": row.get("skill_version"),
                "strategy": row.get("strategy"),
                "outputs": row.get("outputs", []),
            }
            for row in skill_guidance
        ],
        "shot_language": dict(shot_language),
        "continuity": dict(continuity_context),
    }
    if not any((effective_intent, skill_guidance, shot_language, continuity_context)):
        return base_prompt
    encoded = json.dumps(
        guidance,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    if len(encoded) > 20_000:
        raise WorkbenchExecutionError(
            "frozen effective creative intent is too large",
            details={"code": "EFFECTIVE_CREATIVE_INTENT_TOO_LARGE"},
        )
    return f"{base_prompt}\n\n[FROZEN_EFFECTIVE_CREATIVE_INTENT]\n{encoded}"


class WorkbenchExecutionService:
    """Professional workbench execution orchestration (P4-05)."""

    def __init__(self, session: AsyncSession, *, user_id: UUID) -> None:
        self._session = session
        self._user_id = user_id

    async def _hydrate_and_validate_references(
        self,
        *,
        project: Project,
        shot_id: UUID,
        stage: PlanStage,
        references: list[ShotReferenceIntent],
    ) -> list[ShotReferenceIntent]:
        """Validate reference lineage before model resolution or graph writes.

        ``ShotReferenceIntent`` deliberately carries identity rather than
        bytes/URLs.  UUID foreign keys therefore are not enough to prove that
        a reference belongs to this Project/Shot.  Resolve the persisted
        Binding/AssetVersion relationship here and hydrate MIME/fingerprint
        from the authoritative Artifact row so the compiler and the frozen
        plan cannot be driven by client-supplied display metadata.
        """

        shot = await self._session.scalar(
            select(Shot).where(Shot.id == shot_id, Shot.project_id == project.id)
        )
        if shot is None:
            raise WorkbenchExecutionError(
                "shot not found",
                details={"code": "SHOT_NOT_FOUND"},
            )
        if not references:
            return []

        binding_ids = {reference.binding_id for reference in references if reference.binding_id}
        bindings: dict[UUID, ShotReferenceBinding] = {}
        if binding_ids:
            binding_rows = (
                (
                    await self._session.execute(
                        select(ShotReferenceBinding).where(
                            ShotReferenceBinding.id.in_(binding_ids),
                            ShotReferenceBinding.project_id == project.id,
                            ShotReferenceBinding.shot_id == shot.id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            bindings = {binding.id: binding for binding in binding_rows}

        artifact_ids = {reference.artifact_id for reference in references if reference.artifact_id}
        artifact_rows = (
            (
                await self._session.execute(
                    select(Artifact).where(
                        Artifact.id.in_(artifact_ids),
                        Artifact.project_id == project.id,
                    )
                )
            )
            .scalars()
            .all()
        )
        artifacts = {artifact.id: artifact for artifact in artifact_rows}

        version_ids = {
            reference.asset_version_id for reference in references if reference.asset_version_id
        }
        versions: dict[UUID, AssetVersion] = {}
        if version_ids:
            version_rows = (
                (
                    await self._session.execute(
                        select(AssetVersion).where(
                            AssetVersion.id.in_(version_ids),
                            AssetVersion.project_id == project.id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            versions = {version.id: version for version in version_rows}

        hydrated: list[ShotReferenceIntent] = []
        expected_stage = "image" if stage == "image_keyframe" else "video"
        for reference in references:
            if reference.artifact_id is None:
                raise WorkbenchExecutionError(
                    "reference is missing a concrete artifact_id",
                    details={"code": "REFERENCE_ARTIFACT_REQUIRED"},
                )
            artifact = artifacts.get(reference.artifact_id)
            if artifact is None:
                raise WorkbenchExecutionError(
                    "reference artifact does not belong to the current project",
                    details={"code": "REFERENCE_PROJECT_MISMATCH"},
                )

            binding: ShotReferenceBinding | None = None
            if reference.binding_id is not None:
                binding = bindings.get(reference.binding_id)
                if binding is None:
                    raise WorkbenchExecutionError(
                        "reference binding does not belong to the current shot",
                        details={"code": "REFERENCE_BINDING_MISMATCH"},
                    )
                if binding.purpose != reference.purpose:
                    raise WorkbenchExecutionError(
                        "reference purpose does not match its binding",
                        details={"code": "REFERENCE_BINDING_MISMATCH"},
                    )
                if binding.stage not in {"both", expected_stage}:
                    raise WorkbenchExecutionError(
                        "reference binding is not enabled for this execution stage",
                        details={"code": "REFERENCE_STAGE_MISMATCH"},
                    )

            version_id = reference.asset_version_id
            if binding is not None:
                if binding.resolution_mode == "direct_artifact":
                    if binding.artifact_id != artifact.id:
                        raise WorkbenchExecutionError(
                            "reference artifact does not match its binding",
                            details={"code": "REFERENCE_LINEAGE_MISMATCH"},
                        )
                elif binding.resolution_mode == "pinned_version":
                    version_id = binding.asset_version_id
                else:
                    asset = await self._session.scalar(
                        select(Asset).where(
                            Asset.id == binding.asset_id,
                            Asset.project_id == project.id,
                        )
                    )
                    if asset is None or asset.current_version_id is None:
                        raise WorkbenchExecutionError(
                            "reference asset has no current formal version",
                            details={"code": "REFERENCE_NOT_RESOLVED"},
                        )
                    version_id = asset.current_version_id

            if version_id is not None:
                version = versions.get(version_id)
                if version is None:
                    version = await self._session.scalar(
                        select(AssetVersion).where(
                            AssetVersion.id == version_id,
                            AssetVersion.project_id == project.id,
                        )
                    )
                if version is None:
                    raise WorkbenchExecutionError(
                        "reference asset version does not belong to the current project",
                        details={"code": "REFERENCE_PROJECT_MISMATCH"},
                    )
                linked = await self._session.scalar(
                    select(AssetVersionReference.id).where(
                        AssetVersionReference.asset_version_id == version.id,
                        AssetVersionReference.artifact_id == artifact.id,
                        AssetVersionReference.project_id == project.id,
                    )
                )
                if linked is None:
                    raise WorkbenchExecutionError(
                        "reference artifact is not part of the selected asset version",
                        details={"code": "REFERENCE_LINEAGE_MISMATCH"},
                    )

            hydrated.append(
                reference.model_copy(
                    update={
                        "asset_version_id": version_id,
                        "mime_type": artifact.mime_type or reference.mime_type,
                        "fingerprint": artifact.content_hash,
                    }
                )
            )
        return hydrated

    async def _authoritative_creative_input(
        self,
        *,
        project: Project,
        execution_input: WorkbenchExecutionInput,
    ) -> tuple[str, dict[str, JsonValue]]:
        shot = await self._session.scalar(
            select(Shot).where(
                Shot.id == execution_input.shot_id,
                Shot.project_id == project.id,
            )
        )
        if shot is None:
            raise WorkbenchExecutionError(
                "shot not found",
                details={"code": "SHOT_NOT_FOUND"},
            )
        if (
            execution_input.expected_shot_version is not None
            and shot.version != execution_input.expected_shot_version
        ):
            raise WorkbenchExecutionError(
                "shot changed before execution plan preview",
                details={
                    "code": "SHOT_VERSION_MISMATCH",
                    "expected_version": execution_input.expected_shot_version,
                    "actual_version": shot.version,
                },
            )
        configured_prompt = (
            shot.image_prompt if execution_input.stage == "image_keyframe" else shot.video_prompt
        )
        base_prompt = (configured_prompt or "").strip() or shot.visual_description.strip()
        if not base_prompt:
            raise WorkbenchExecutionError(
                "saved Shot has no executable prompt",
                details={"code": "SHOT_PROMPT_REQUIRED"},
            )
        if execution_input.prompt.strip() != base_prompt:
            raise WorkbenchExecutionError(
                "submitted prompt does not match the saved Shot design",
                details={"code": "EXECUTION_PROMPT_MISMATCH"},
            )

        scene = await self._session.scalar(
            select(Scene)
            .join(Episode, Episode.id == Scene.episode_id)
            .where(
                Scene.id == shot.scene_id,
                Episode.project_id == project.id,
            )
        )
        if scene is None:
            raise WorkbenchExecutionError(
                "scene not found",
                details={"code": "SCENE_NOT_FOUND"},
            )
        scene_design = _mapping(scene.design_state)
        shot_state = _mapping(shot.director_state)
        scene_snapshot = _mapping(scene_design.get("creative_capabilities"))
        shot_snapshot = _mapping(shot_state.get("creative_capabilities"))
        effective_intent = _deep_merge(
            _mapping(scene_snapshot.get("effective_intent")),
            _mapping(shot_snapshot.get("effective_intent")),
        )
        value_sources = {
            **{
                str(key): str(value)
                for key, value in _mapping(scene_snapshot.get("value_sources")).items()
            },
            **{
                str(key): str(value)
                for key, value in _mapping(shot_snapshot.get("value_sources")).items()
            },
        }
        skills = _skill_guidance(scene_snapshot, shot_snapshot)
        shot_language = _deep_merge(
            _mapping(scene_snapshot.get("shot_director_intent_patch")),
            _mapping(shot_snapshot.get("shot_director_intent_patch")),
        )
        continuity_context = _mapping(scene_design.get("continuity_context"))
        prompt = _compose_effective_prompt(
            base_prompt=base_prompt,
            effective_intent=effective_intent,
            skill_guidance=skills,
            shot_language=shot_language,
            continuity_context=continuity_context,
        )
        director_state = dict(shot_state)
        director_state.pop("creative_capabilities", None)
        request_tags = {
            key: value
            for key, value in execution_input.semantic_intent.items()
            if key in {"repair"}
        }
        semantic: dict[str, JsonValue] = {
            "intent": (
                "shot_keyframe" if execution_input.stage == "image_keyframe" else "shot_video"
            ),
            "project_id": str(project.id),
            "scene_id": str(scene.id),
            "shot_id": str(shot.id),
            "shot_version": shot.version,
            "scene_version": scene.version,
            "visual_description": shot.visual_description,
            "director_state": cast(JsonValue, director_state),
            "effective_creative_intent": cast(JsonValue, effective_intent),
            "creative_value_sources": cast(JsonValue, value_sources),
            "skill_guidance": cast(JsonValue, skills),
            "shot_language": cast(JsonValue, shot_language),
            "continuity_context": cast(JsonValue, continuity_context),
            "creative_snapshot_hashes": cast(
                JsonValue,
                {
                    "scene": scene_snapshot.get("compiled_hash"),
                    "shot": shot_snapshot.get("compiled_hash"),
                },
            ),
            "request_tags": cast(JsonValue, request_tags),
        }
        # Repair is the sole allow-listed caller tag. Keep its historical
        # top-level shape for Worker/trace compatibility while also grouping
        # all caller tags under request_tags for inspection.
        semantic.update(request_tags)
        return prompt, semantic

    async def build_plan(
        self,
        *,
        project: Project,
        execution_input: WorkbenchExecutionInput,
        allow_unaccepted_approximations: bool = False,
    ) -> WorkbenchExecutionPlan:
        """Resolve model, compile references and freeze a WorkbenchExecutionPlan.

        Fails closed (raises) when the model is unavailable or when capability
        gaps remain (unsupported references are never silently dropped).
        """
        prompt, semantic_intent = await self._authoritative_creative_input(
            project=project,
            execution_input=execution_input,
        )
        references = await self._hydrate_and_validate_references(
            project=project,
            shot_id=execution_input.shot_id,
            stage=execution_input.stage,
            references=list(execution_input.references),
        )
        slot, capability, purpose, _node_key = _STAGE_CONTRACT[execution_input.stage]
        resolution = await ExecutionModelResolver(self._session).resolve(
            project=project,
            slot=slot,
            capability=capability,
            purpose=purpose,
            mode_id=execution_input.mode_id,
            requested_model_id=execution_input.requested_model_id,
            requested_binding_id=execution_input.requested_binding_id,
        )
        if resolution.status != "RESOLVED" or resolution.catalog_entry_id is None:
            raise WorkbenchExecutionError(
                f"selected execution model is unavailable: {resolution.reason or resolution.status}"
            )

        # Connection / credential revision identity for the plan (07 §16).
        connection_revision_id: UUID | None = None
        credential_revision_id: UUID | None = None
        if resolution.provider_connection_id is not None:
            connection = await self._session.get(
                ProviderConnection, resolution.provider_connection_id
            )
            if connection is None or connection.workspace_id != project.workspace_id:
                raise WorkbenchExecutionError("resolved provider connection is unavailable")
            current_revision = await self._session.scalar(
                select(ProviderConnectionRevision)
                .where(
                    ProviderConnectionRevision.connection_id == resolution.provider_connection_id
                )
                .order_by(ProviderConnectionRevision.revision_no.desc())
                .limit(1)
            )
            if current_revision is not None:
                connection_revision_id = current_revision.id
                credential_revision_id = current_revision.credential_revision_id
        if connection_revision_id is None or credential_revision_id is None:
            raise WorkbenchExecutionError("resolved provider connection revision is unavailable")
        # Carry the immutable revision identity with the typed model
        # resolution.  The worker must be able to reconstruct the exact
        # Provider runtime without resolving the mutable connection again.
        resolution = resolution.model_copy(
            update={
                "provider_connection_revision_id": connection_revision_id,
                "credential_revision_id": credential_revision_id,
            }
        )

        entry = await self._session.get(ModelCatalogEntry, resolution.catalog_entry_id)
        if entry is None:
            raise WorkbenchExecutionError("resolved catalog entry not found")
        capability_manifest = ModelCapabilityManifest.model_validate(entry.capability_manifest_json)
        v3_manifest = to_v3_model_manifest(
            capability_manifest,
            transport_profile_id="workbench",
        )

        if execution_input.stage == "video":
            # Video execution requires the shot formal keyframe; the latest
            # image must never be used as a fallback (03 §38/§39).
            shot = await self._session.get(Shot, execution_input.shot_id)
            if shot is None or shot.project_id != project.id:
                raise WorkbenchExecutionError("shot not found")
            try:
                formal = await require_formal_keyframe(
                    self._session,
                    project_id=project.id,
                    shot_id=execution_input.shot_id,
                )
            except ValidationAppError as exc:
                raise WorkbenchExecutionError(str(exc)) from exc
            if not any(ref.artifact_id == formal.id for ref in references):
                references.insert(
                    0,
                    ShotReferenceIntent(
                        purpose="first_frame",
                        artifact_id=formal.id,
                        mime_type=formal.mime_type,
                    ),
                )

        compiled = compile_references(
            manifest=v3_manifest,
            capability=capability,
            references=references,
            mode_id=execution_input.mode_id,
            accept_approximations=execution_input.accept_approximations,
        )

        plan = WorkbenchExecutionPlan(
            project_id=project.id,
            shot_id=execution_input.shot_id,
            shot_experiment_id=execution_input.shot_experiment_id,
            stage=execution_input.stage,
            prompt=prompt,
            semantic_intent=semantic_intent,
            mode_id=execution_input.mode_id,
            resolved_model=resolution,
            capability=capability,
            planned_references=compiled.planned_references,
            capability_gaps=compiled.capability_gaps,
            semantic_request_preview={
                "intent": semantic_intent,
                "references": len(compiled.planned_references),
            },
            connection_revision_id=connection_revision_id,
            credential_revision_id=credential_revision_id,
            accepted_approximations=compiled.accepted_approximations,
            expected_shot_version=execution_input.expected_shot_version,
        ).freeze()

        # Fail closed on any remaining capability gap (fatal gaps always remain;
        # warning gaps disappear only when the caller accepted approximations).
        blocking_gaps = [
            gap
            for gap in plan.capability_gaps
            if gap.severity == "fatal" or not allow_unaccepted_approximations
        ]
        if blocking_gaps:
            reasons = "; ".join(gap.reason for gap in blocking_gaps)
            raise WorkbenchExecutionError(f"workbench plan has capability gaps: {reasons}")
        return plan

    async def lock_command_scope(self, *, project_id: UUID) -> None:
        # Command keys are unique per project, including accidental reuse on
        # different Shots. Serialize the short DB-only queueing transaction.
        await self._session.execute(
            select(Project.id).where(Project.id == project_id).with_for_update()
        )

    async def find_command_receipt(
        self, *, project_id: UUID, shot_id: UUID, stage: PlanStage,
        command_key: str | None, plan_fingerprint: str | None = None,
        expected_request_hash: str | None = None,
    ) -> NodeRun | None:
        """Read a committed frozen receipt; never resolve or submit a model."""
        if command_key is not None and not command_key.strip():
            raise ValidationAppError("Idempotency-Key must not be blank")
        if command_key is None and not plan_fingerprint:
            return None
        key = _workbench_idempotency_key(
            stage=stage, override=command_key, plan_fingerprint=plan_fingerprint or "",
        )
        run = await self._session.scalar(select(NodeRun).where(
            NodeRun.project_id == project_id, NodeRun.idempotency_key == key,
        ))
        if run is None:
            return None
        snapshot = run.input_snapshot or {}
        graph_shot = await self._session.scalar(
            select(ProductionGraph.scope_entity_id)
            .join(GraphVersion, GraphVersion.graph_id == ProductionGraph.id)
            .where(GraphVersion.id == run.graph_version_id,
                   ProductionGraph.project_id == project_id, ProductionGraph.scope_type == "shot")
        )
        if (graph_shot != shot_id or snapshot.get("shot_id") != str(shot_id)
                or snapshot.get("stage") != stage):
            raise ConflictError(
                "Execution command key belongs to a different Shot or stage",
                details={"code": "EXECUTION_COMMAND_SCOPE_CONFLICT"},
            )
        if expected_request_hash is not None and (
            snapshot.get("workbench_request_hash") != expected_request_hash
            or (plan_fingerprint is not None
                and snapshot.get("plan_fingerprint") != plan_fingerprint)
        ):
            raise ConflictError(
                "Execution command key was already used with a different request",
                details={"code": "EXECUTION_COMMAND_REUSED", "node_run_id": str(run.id)},
            )
        return run

    async def create_and_dispatch(
        self,
        *,
        project: Project,
        execution_input: WorkbenchExecutionInput,
        idempotency_key_override: str | None = None,
        prepared_plan: WorkbenchExecutionPlan | None = None,
        request_hash: str | None = None,
    ) -> NodeRun:
        """Resolve the shot graph, create a queued NodeRun and persist the
        frozen plan snapshot for the worker.

        The NodeRun ``status="queued"`` is the dispatch: the worker claims and
        executes it. No direct Provider HTTP, no legacy budget / agent gate.
        """
        identity = request_hash or workbench_request_hash(execution_input.model_dump(mode="json"))
        await self.lock_command_scope(project_id=project.id)
        existing = await self.find_command_receipt(
            project_id=project.id, shot_id=execution_input.shot_id, stage=execution_input.stage,
            command_key=idempotency_key_override,
            plan_fingerprint=prepared_plan.plan_fingerprint if prepared_plan else None,
            expected_request_hash=identity,
        )
        if existing is not None:
            return existing
        plan = prepared_plan or await self.build_plan(
            project=project,
            execution_input=execution_input,
        )
        existing = await self.find_command_receipt(
            project_id=project.id, shot_id=execution_input.shot_id, stage=execution_input.stage,
            command_key=idempotency_key_override, plan_fingerprint=plan.plan_fingerprint,
            expected_request_hash=identity,
        )
        if existing is not None:
            return existing
        if (
            plan.plan_fingerprint is None
            or plan.project_id != project.id
            or plan.shot_id != execution_input.shot_id
            or plan.stage != execution_input.stage
        ):
            raise WorkbenchExecutionError(
                "prepared workbench plan does not match the execution input",
                details={"code": "EXECUTION_PLAN_INVALID"},
            )
        _slot, _capability, _purpose, node_key = _STAGE_CONTRACT[execution_input.stage]

        graphs = GraphService(self._session)
        # One graph per shot scope (P4-06): reuse the existing shot graph when
        # present, otherwise create it.
        graph = await self._session.scalar(
            select(ProductionGraph).where(
                ProductionGraph.project_id == project.id,
                ProductionGraph.scope_type == "shot",
                ProductionGraph.scope_entity_id == execution_input.shot_id,
            )
        )
        if graph is None:
            graph = await graphs.create_graph(
                project_id=project.id,
                scope_type="shot",
                scope_entity_id=execution_input.shot_id,
                template_key=SHOT_PIPELINE_TEMPLATE_KEY,
                created_by=self._user_id,
                definition=shot_pipeline_definition(
                    shot_id=str(execution_input.shot_id),
                    shot={"prompt": execution_input.prompt},
                    workbench_plan=plan.model_dump(mode="json"),
                ),
            )
        assert graph.current_version_id is not None
        materialized = await graphs.materialize_definition(version_id=graph.current_version_id)
        version = materialized.version
        if version.status == GraphStatus.DRAFT.value:
            version = await graphs.publish(
                version_id=version.id,
                published_by=self._user_id,
            )
        node = materialized.nodes[node_key]
        await self._session.execute(
            select(GraphNode.id).where(GraphNode.id == node.id).with_for_update()
        )
        previous_run = await self._session.scalar(
            select(NodeRun).where(NodeRun.graph_node_id == node.id)
            .order_by(NodeRun.attempt_no.desc()).limit(1)
        )
        attempt_no = (previous_run.attempt_no if previous_run is not None else 0) + 1
        await _ensure_pure_chain_upstreams(
            self._session,
            project_id=project.id,
            graph_version_id=version.id,
            target_node_id=node.id,
            shot_id=execution_input.shot_id,
            prompt=plan.prompt,
            stage=plan.stage,
            created_by=self._user_id,
        )
        provider_connection_id = plan.resolved_model.provider_connection_id
        if provider_connection_id is None:
            raise WorkbenchExecutionError("frozen execution model has no provider connection")
        provider_connection = await self._session.get(ProviderConnection, provider_connection_id)
        if provider_connection is None or provider_connection.workspace_id != project.workspace_id:
            raise WorkbenchExecutionError("frozen provider connection is unavailable")

        snapshot: dict[str, object] = {
            "workbench_plan": plan.model_dump(mode="json"),
            "workbench_request_hash": identity,
            # Keep the compiled selection visible at the NodeRun boundary as
            # well as inside the typed plan.  The Worker consumes this frozen
            # list; it must never re-resolve mutable Asset/Binding state.
            "references": [
                reference.model_dump(mode="json") for reference in plan.planned_references
            ],
            "plan_fingerprint": plan.plan_fingerprint,
            "stage": plan.stage,
            "mode_id": plan.mode_id,
            "prompt": plan.prompt,
            "project_id": str(project.id),
            "shot_id": str(execution_input.shot_id),
            "node_key": node_key,
            "source_commit": get_settings().source_commit,
            # Professional Workbench media NodeRuns always enter the unified
            # Provider path. These keys make the frozen resolution explicit at
            # the worker boundary.
            "professional_unified": True,
            "execution_path": "unified-v1",
            "model_binding_id": str(plan.resolved_model.provider_model_binding_id),
            "capability_manifest_hash": plan.resolved_model.manifest_hash,
            "connection_revision_id": str(plan.connection_revision_id),
            "credential_revision_id": str(plan.credential_revision_id),
            "execution_model_resolution": plan.resolved_model.model_dump(mode="json"),
            "selection_plan": {
                "purpose": "keyframe" if plan.stage == "image_keyframe" else "video",
                "mode": plan.mode_id,
                "mode_id": plan.mode_id,
                "model_binding_id": str(plan.resolved_model.provider_model_binding_id),
                "provider_type": provider_connection.provider_type,
                "protocol_profile": provider_connection.protocol_profile,
                "catalog_entry_id": str(plan.resolved_model.catalog_entry_id),
                "model_id": plan.resolved_model.resolved_model_id.rsplit("/", 1)[-1]
                if plan.resolved_model.resolved_model_id
                else None,
                "invoke_model_value": plan.resolved_model.invoke_model_value,
                "connection_id": str(plan.resolved_model.provider_connection_id),
                "manifest_hash": plan.resolved_model.manifest_hash,
                "execution_model_resolution": plan.resolved_model.model_dump(mode="json"),
                "evidence": {"professional_unified": True},
            },
            "plan": {"prompt": plan.prompt},
        }
        if plan.stage == "video":
            # The current Workbench API intentionally exposes no separate
            # duration control.  The verified video manifests use the
            # canonical five-second product intent, which is also the safe
            # default used by the unified compiler.
            snapshot["duration_seconds"] = 5
            snapshot["aspect_ratio"] = project.aspect_ratio
        input_hash = _node_run_input_hash(snapshot)
        node_run = NodeRun(
            project_id=project.id,
            graph_version_id=version.id,
            graph_node_id=node.id,
            attempt_no=attempt_no,
            parent_run_id=previous_run.id if previous_run is not None else None,
            idempotency_key=_workbench_idempotency_key(
                stage=plan.stage,
                override=idempotency_key_override,
                plan_fingerprint=plan.plan_fingerprint or input_hash,
            ),
            input_hash=input_hash,
            status="queued",
            input_snapshot=snapshot,
            created_by=self._user_id,
        )
        self._session.add(node_run)
        await self._session.flush()
        return node_run

    async def get_recent_plan(
        self,
        *,
        project_id: UUID,
        shot_id: UUID,
        stage: PlanStage,
        limit: int = 20,
    ) -> list[WorkbenchExecutionPlan]:
        """Read back frozen plan snapshots (preview / trace support)."""
        rows = (
            (
                await self._session.execute(
                    select(NodeRun)
                    .where(
                        NodeRun.project_id == project_id,
                        NodeRun.input_snapshot["shot_id"].as_string() == str(shot_id),
                    )
                    .order_by(NodeRun.created_at.desc())
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        plans: list[WorkbenchExecutionPlan] = []
        for run in rows:
            raw = (run.input_snapshot or {}).get("workbench_plan")
            if not isinstance(raw, dict):
                continue
            try:
                plans.append(WorkbenchExecutionPlan.model_validate(raw))
            except Exception:  # noqa: BLE001 - tolerate malformed historical rows
                continue
        return plans
