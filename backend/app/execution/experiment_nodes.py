"""Canonical preparation of experimental NodeRuns.

Experiments reuse the same graph, frozen model identity and Worker runtime as
the formal Workbench path. This module only prepares an isolated experiment
branch; it does not expose review, lock, upload, or direct-shot operations.
"""

from __future__ import annotations

import hashlib
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project
from app.assets.models import Shot
from app.config import get_settings
from app.consistency.identity_policy import identity_evidence_policy_snapshot
from app.execution.branches import branch_priority
from app.execution.models import Artifact, NodeRun
from app.execution.product_path import identity_priority_keyframe_prompt
from app.execution.shot_locks import is_shot_locked
from app.execution.shot_pipeline import (
    SHOT_EDGES,
    SHOT_NODES,
    SHOT_PIPELINE_TEMPLATE_KEY,
    shot_pipeline_definition,
)
from app.shared.errors import NotFoundError, ValidationAppError

DONE_STATUSES: frozenset[str] = frozenset({"completed", "cached", "completed_after_cancel"})


async def get_shot_or_404(session: AsyncSession, *, project_id: UUID, shot_id: UUID) -> Shot:
    shot = await session.get(Shot, shot_id)
    if shot is None or shot.project_id != project_id:
        raise NotFoundError("shot not found")
    return shot


def _shot_runs(runs: list[NodeRun], shot_id: UUID) -> list[NodeRun]:
    sid = str(shot_id)
    return [
        r
        for r in runs
        if (r.input_snapshot or {}).get("shot_id") == sid or sid in str(r.idempotency_key)
    ]


def _latest_by_node_key(
    runs: list[NodeRun],
    *,
    target_snapshot: dict[str, object] | None = None,
) -> dict[str, NodeRun]:
    """Map node_key → latest eligible NodeRun for one execution branch."""
    by_key: dict[str, NodeRun] = {}
    for r in runs:
        priority = branch_priority(r.input_snapshot, target_snapshot)
        if priority is None:
            continue
        key = str((r.input_snapshot or {}).get("node_key") or "")
        if not key:
            continue
        prev = by_key.get(key)
        if prev is None:
            by_key[key] = r
            continue
        previous_priority = branch_priority(prev.input_snapshot, target_snapshot) or 0
        if (priority, int(r.attempt_no or 0), r.created_at, str(r.id)) >= (
            previous_priority,
            int(prev.attempt_no or 0),
            prev.created_at,
            str(prev.id),
        ):
            by_key[key] = r
    return by_key


def _missing_required_prerequisites(
    *,
    requested_keys: list[str],
    latest_by_key: dict[str, NodeRun],
) -> list[str]:
    """Return absent/failed ancestors needed to make a partial rerun executable.

    A local rerun invalidates the changed node and its real downstream, but a
    downstream node can also have independent required inputs.  For example,
    ``composite`` needs ``video_drift_review``, ``voice`` and ``subtitle``.
    Reusing a completed/queued/running ancestor is correct; silently omitting an
    ancestor that has never been materialized (or has terminally failed) is not.
    """
    requested = set(requested_keys)
    required: set[str] = set()
    visited: set[str] = set()
    upstream_by_downstream: dict[str, list[str]] = {}
    for upstream, downstream in SHOT_EDGES:
        upstream_by_downstream.setdefault(downstream, []).append(upstream)

    def visit(node_key: str) -> None:
        if node_key in visited:
            return
        visited.add(node_key)
        for upstream in upstream_by_downstream.get(node_key, []):
            if upstream in requested:
                visit(upstream)
                continue
            latest = latest_by_key.get(upstream)
            if latest is not None and latest.status in {
                *DONE_STATUSES,
                "queued",
                "running",
            }:
                continue
            required.add(upstream)
            visit(upstream)

    for key in requested_keys:
        visit(key)
    return [key for key in SHOT_NODES if key in required and key not in requested]


async def _freeze_execution_model_resolution(
    session: AsyncSession,
    *,
    project: Project,
    node_key: str,
) -> dict[str, object]:
    """Freeze the concrete ProviderModelBinding for unified media nodes at dispatch.

    V2 §Phase 5 boundary: NodeRun creation must pin the binding/catalog/connection
    identity so the worker cannot re-resolve a newer binding at submission time
    (Gate: 旧任务不会读取新的 Binding). The worker already treats a snapshot
    ``model_binding_id`` as ``explicit_binding`` and fail-closes on mismatch, so
    this freeze is the missing dispatch half. Voice/TTS has no A+B media binding
    (local TTS has no remote model binding), so only keyframe/video freeze here.
    Never raises — an unavailable resolution is recorded as an explicit audit
    marker, and execution fail-closes with MODEL_BINDING_UNAVAILABLE (never
    silently runs a different model).
    """
    from app.providers.capabilities import Capability
    from app.providers.model_profiles.slots import ModelSlot
    from app.providers.model_resolution import ExecutionModelResolver

    slot_cap_purpose: dict[str, tuple[ModelSlot, Capability, str]] = {
        "keyframe": (ModelSlot.VISUAL_KEYFRAME, Capability.IMAGE_GENERATE, "keyframe"),
        # P0 shots always carry a keyframe as the video's first frame.
        "video": (
            ModelSlot.VIDEO_SHOT,
            Capability.VIDEO_IMAGE_TO_VIDEO,
            "video",
        ),
    }
    pair = slot_cap_purpose.get(node_key)
    if pair is None:
        return {}
    slot, capability, purpose = pair
    try:
        resolution = await ExecutionModelResolver(session).resolve(
            project=project,
            slot=slot,
            capability=capability,
            purpose=purpose,
            mode_id="explicit_binding",
        )
    except Exception as exc:  # noqa: BLE001 - audit path, never block dispatch
        return {
            "model_binding_id": None,
            "model_resolution_unavailable_reason": (
                f"{type(exc).__name__}: {str(exc)[:120]}"
            ),
        }
    if resolution.status != "RESOLVED" or resolution.provider_model_binding_id is None:
        return {
            "model_binding_id": None,
            "model_resolution_unavailable_reason": (
                resolution.reason or resolution.status
            ),
        }
    return {
        "model_binding_id": str(resolution.provider_model_binding_id),
        "execution_model_resolution": resolution.model_dump(mode="json"),
    }


async def queue_branch_nodes(
    session: AsyncSession,
    *,
    project_id: UUID,
    shot_id: UUID,
    user_id: UUID,
    node_keys: list[str] | None = None,
    force: bool = False,
    include_missing_dependencies: bool = False,
    experiment_id: UUID | None = None,
    model_binding_id: UUID | None = None,
    model_binding_node_key: str | None = None,
) -> list[UUID]:
    """Queue branch NodeRuns with persisted Workbench context.

    This helper is used only by the explicit Experiment API and adoption flow.
    The formal user-facing path is WorkbenchExecutionService; it never calls a
    Provider directly and does not expose a direct Shot operation.
    """
    if await is_shot_locked(session, project_id=project_id, shot_id=shot_id):
        raise ValidationAppError("shot is human-locked")
    keys = node_keys or list(SHOT_NODES)
    for k in keys:
        if k not in SHOT_NODES:
            raise ValidationAppError(f"unknown node key: {k}")
    if experiment_id is None and (model_binding_id is not None or model_binding_node_key):
        raise ValidationAppError("model override requires an experiment branch")
    if model_binding_node_key is not None and model_binding_node_key not in {
        "keyframe",
        "video",
        "voice",
    }:
        raise ValidationAppError("model override node must be keyframe, video, or voice")

    from app.access.models import Project
    from app.production.models import GraphVersion, ProductionGraph
    from app.production.service import GraphService

    project = await session.get(Project, project_id)
    assert project is not None
    shot = await get_shot_or_404(session, project_id=project_id, shot_id=shot_id)
    graphs = GraphService(session)
    existing = (
        await session.execute(
            select(ProductionGraph).where(
                ProductionGraph.project_id == project_id,
                ProductionGraph.scope_type == "shot",
                ProductionGraph.scope_entity_id == shot_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        graph = existing
        if graph.current_version_id is None:
            graph = await graphs.create_graph(
                project_id=project_id,
                scope_type="shot",
                scope_entity_id=shot_id,
                template_key=SHOT_PIPELINE_TEMPLATE_KEY,
                created_by=user_id,
                definition=shot_pipeline_definition(),
            )
    else:
        graph = await graphs.create_graph(
            project_id=project_id,
            scope_type="shot",
            scope_entity_id=shot_id,
            template_key=SHOT_PIPELINE_TEMPLATE_KEY,
            created_by=user_id,
            definition=shot_pipeline_definition(),
        )
    assert graph.current_version_id is not None
    version_id = graph.current_version_id
    version = await session.get(GraphVersion, version_id)
    materialized = await graphs.materialize_definition(version_id=version_id)
    if version is not None and version.status == "draft":
        version = await graphs.publish(version_id=version_id, published_by=user_id)
    definition = dict(version.definition or {}) if version is not None else {}
    shot_plan = definition.get("shot")
    if not isinstance(shot_plan, dict):
        shot_plan = {}
    visual = str(
        shot_plan.get("visual_description") or shot.visual_description or f"Shot {shot.shot_number}"
    ).strip()
    dialogue = str(shot_plan.get("dialogue") or shot.dialogue or "").strip()
    keyframe_prompt = str(
        shot_plan.get("keyframe_prompt") or shot_plan.get("prompt") or visual
    ).strip()

    existing_runs = list(
        (
            await session.execute(
                select(NodeRun).where(
                    NodeRun.project_id == project_id,
                    NodeRun.graph_version_id == version_id,
                )
            )
        )
        .scalars()
        .all()
    )
    target_snapshot: dict[str, object] = {}
    if experiment_id is not None:
        target_snapshot["experiment_id"] = str(experiment_id)
    latest_by_key = _latest_by_node_key(
        _shot_runs(existing_runs, shot_id),
        target_snapshot=target_snapshot,
    )
    if include_missing_dependencies:
        keys = [
            *keys,
            *_missing_required_prerequisites(
                requested_keys=keys,
                latest_by_key=latest_by_key,
            ),
        ]
    canonical_binding: dict[str, object] = {}
    canonical_locked_prompt = ""
    prior_keyframe = latest_by_key.get("keyframe")
    if prior_keyframe is not None:
        keyframe_snapshot = prior_keyframe.input_snapshot or {}
        for field in (
            "canonical_artifact_id",
            "canonical_object_key",
            "canonical_content_hash",
            "canonical_mime_type",
        ):
            if keyframe_snapshot.get(field) is not None:
                canonical_binding[field] = keyframe_snapshot[field]
        candidate_prompt = keyframe_snapshot.get("canonical_locked_prompt")
        if isinstance(candidate_prompt, str):
            canonical_locked_prompt = candidate_prompt
    probe_binding: dict[str, object] = {}
    if prior_keyframe is not None and prior_keyframe.result_artifact_id is not None:
        artifact = await session.get(Artifact, prior_keyframe.result_artifact_id)
        if artifact is not None:
            probe_binding = {
                "probe_artifact_id": str(artifact.id),
                "probe_object_key": artifact.object_key,
                "probe_content_hash": artifact.content_hash,
                "probe_mime_type": artifact.mime_type,
            }

    run_ids: list[UUID] = []
    for key in keys:
        node = materialized.nodes[key]
        prior_for_node = [run for run in existing_runs if run.graph_node_id == node.id]
        latest = latest_by_key.get(key)
        if (
            not force
            and latest is not None
            and latest.status in {*DONE_STATUSES, "queued", "running"}
        ):
            continue
        ih = hashlib.sha256(f"{shot_id}:{key}:{uuid4()}".encode()).hexdigest()
        attempt = len(prior_for_node) + 1
        prompt = (
            keyframe_prompt
            if key == "keyframe"
            else f"{key}: {visual}\nDialogue: {dialogue}\nShot: {shot_id}"
        )
        lead_identity_value = shot_plan.get("lead_identity_required")
        lead_identity_required = lead_identity_value is True
        # A project with a registered lead canonical is single-lead in P0. Script
        # imports may carry no per-shot lead flag, so infer identity only when the
        # field is absent. An explicit false marks inserts/establishing shots that
        # must not be forced through a lead-face Gate.
        if not isinstance(lead_identity_value, bool) and canonical_binding:
            lead_identity_required = True
        if key == "keyframe" and lead_identity_required and canonical_locked_prompt:
            prompt = identity_priority_keyframe_prompt(
                prompt,
                canonical_locked_prompt=canonical_locked_prompt,
            )
        model_profile: dict[str, object] = {}
        execution_freeze: dict[str, object] = {}
        if key in {"keyframe", "video", "voice"}:
            from app.providers.model_profiles.node_snapshot import (
                derive_video_capability,
                planned_node_model_profile,
            )

            video_capability = None
            if key == "video":
                # P0 shots always carry a keyframe as the video's first frame.
                # Extend here when shots declare last-frame / reference inputs
                # (spec §43 derivation order).
                video_capability = derive_video_capability(
                    first_frame=True, last_frame=False, references=False
                )
            model_profile = await planned_node_model_profile(
                session,
                project=project,
                node_key=key,
                video_capability=video_capability,
            )
        if key in {"keyframe", "video"}:
            # V2 §Phase 5: freeze the concrete binding at dispatch so the worker
            # submits against the same model the operator reviewed, never a newer
            # binding picked up after the run was created.
            execution_freeze = await _freeze_execution_model_resolution(
                session,
                project=project,
                node_key=key,
            )
        snapshot: dict[str, object] = {
            "shot_id": str(shot_id),
            "node_key": key,
            "execution_branch": "experiment" if experiment_id is not None else "formal",
            "source_commit": get_settings().source_commit,
            "plan_id": definition.get("plan_id"),
            "prompt": prompt,
            "plan": {
                "prompt": keyframe_prompt,
                "shot": shot_plan,
            },
            "visual_description": visual,
            "visual": visual,
            "dialogue": dialogue,
            "duration_seconds": str(shot.duration_seconds),
            "subtitle": dialogue,
            "lead_identity_required": lead_identity_required,
            "identity_evidence_policy": identity_evidence_policy_snapshot(),
            "model_profile": model_profile,
            **execution_freeze,
        }
        if experiment_id is not None:
            snapshot["experiment_id"] = str(experiment_id)
        if model_binding_id is not None and key == model_binding_node_key:
            # Explicit experiment override always wins over the resolver freeze.
            snapshot["model_binding_id"] = str(model_binding_id)
            snapshot["model_profile"] = {
                **model_profile,
                "model_binding_id": str(model_binding_id),
                "source": "experiment_override",
            }
        snapshot.update(canonical_binding)
        if canonical_locked_prompt:
            snapshot["canonical_locked_prompt"] = canonical_locked_prompt
        if key == "identity_review":
            snapshot.update(probe_binding)
        run = NodeRun(
            project_id=project_id,
            graph_version_id=version_id,
            graph_node_id=node.id,
            attempt_no=attempt,
            idempotency_key=f"start:{key}:{shot_id}:{ih}",
            input_hash=ih,
            status="queued",
            input_snapshot=snapshot,
            created_by=user_id,
        )
        session.add(run)
        await session.flush()
        run_ids.append(run.id)
    # Keep shot.status within product vocabulary used by UI/import (avoid unknown enums)
    if shot.status in {"draft", "pending", "review_rejected", "review_passed"}:
        shot.status = "in_production"
    await session.flush()
    return run_ids
