"""Per-shot review, lock, local re-run, and audited manual media (P0)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Shot
from app.config import get_settings
from app.consistency.face_policy import approved_face_policy_snapshot, approved_face_threshold
from app.execution.artifact_lineage import get_or_create_artifact
from app.execution.models import Artifact, NodeRun
from app.execution.product_path import identity_priority_keyframe_prompt
from app.execution.runtime_invariants import mark_stale_downstream
from app.execution.shot_p0 import is_shot_locked, set_shot_lock
from app.execution.shot_pipeline import (
    SHOT_EDGES,
    SHOT_NODES,
    SHOT_PIPELINE_TEMPLATE_KEY,
    shot_pipeline_definition,
)
from app.shared.errors import NotFoundError, ValidationAppError
from app.storage.minio_store import ObjectStore, get_object_store

# Nodes that must be completed (with artifact for media) before human approve.
# Review nodes need completed status; face/continuity must not be blocked.
REQUIRED_APPROVE_NODES: tuple[str, ...] = (
    "keyframe",
    "face_review",
    "video",
    "video_drift_review",
    "voice",
    "subtitle",
    "composite",
    "continuity_review",
)
MEDIA_ARTIFACT_NODES: frozenset[str] = frozenset(
    {"keyframe", "video", "voice", "subtitle", "composite"}
)
DONE_STATUSES: frozenset[str] = frozenset({"completed", "cached", "completed_after_cancel"})


@dataclass(frozen=True)
class ShotReviewResult:
    shot_id: UUID
    status: str
    locked: bool
    message: str


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


def _latest_by_node_key(runs: list[NodeRun]) -> dict[str, NodeRun]:
    """Map node_key → latest NodeRun (by attempt_no then created_at)."""
    by_key: dict[str, NodeRun] = {}
    for r in runs:
        key = str((r.input_snapshot or {}).get("node_key") or "")
        if not key:
            continue
        prev = by_key.get(key)
        if prev is None:
            by_key[key] = r
            continue
        if int(r.attempt_no or 0) >= int(prev.attempt_no or 0):
            by_key[key] = r
    return by_key


async def assert_shot_approvable(session: AsyncSession, *, project_id: UUID, shot_id: UUID) -> None:
    """Fail closed: empty shots or incomplete/blocked pipelines cannot review_passed."""
    runs = list(
        (await session.execute(select(NodeRun).where(NodeRun.project_id == project_id)))
        .scalars()
        .all()
    )
    shot_runs = _shot_runs(runs, shot_id)
    if not shot_runs:
        raise ValidationAppError(
            "APPROVE_GATE: shot has no NodeRuns; produce pipeline before approve"
        )
    by_key = _latest_by_node_key(shot_runs)
    missing: list[str] = []
    incomplete: list[str] = []
    blocked: list[str] = []
    no_artifact: list[str] = []

    for key in REQUIRED_APPROVE_NODES:
        run = by_key.get(key)
        if run is None:
            missing.append(key)
            continue
        if run.status not in DONE_STATUSES:
            incomplete.append(f"{key}:{run.status}")
            continue
        if key in MEDIA_ARTIFACT_NODES and run.result_artifact_id is None:
            # Allow audited manual media linked by delete_reason for this shot/node
            manual = await _has_manual_artifact(
                session, project_id=project_id, shot_id=shot_id, node_key=key
            )
            if not manual:
                no_artifact.append(key)
        if key in {"face_review", "video_drift_review", "continuity_review"}:
            summary = run.output_summary or {}
            status = str(
                summary.get("status")
                or summary.get("review_status")
                or summary.get("face_review")
                or ""
            )
            if key == "video_drift_review":
                # Drift gate is passed-only: blocked/needs_human must be resolved
                # by re-running the video, never bypassed by approve.
                if status == "not_applicable":
                    applicable = (run.input_snapshot or {}).get("lead_identity_required")
                    if applicable is not False:
                        blocked.append("video_drift_review:invalid_not_applicable")
                    continue
                if status != "passed":
                    blocked.append(f"video_drift_review:{status}")
                continue
            if key == "face_review" and status == "not_applicable":
                applicable = (run.input_snapshot or {}).get("lead_identity_required")
                if applicable is not False:
                    blocked.append("face_review:invalid_not_applicable")
                continue
            # Manual audited completion stores status=passed
            if status in {"blocked", "fail", "failed", "reject"}:
                blocked.append(f"{key}:{status}")
            if (
                key == "face_review"
                and (run.input_snapshot or {}).get("lead_identity_required") is True
            ):
                policy = approved_face_policy_snapshot()
                if (run.input_snapshot or {}).get("face_policy") != policy:
                    blocked.append("face_review:policy_mismatch")
                score = summary.get("face_score")
                try:
                    if not isinstance(score, int | float | str):
                        raise TypeError("face score is not numeric")
                    score_ok = float(score) >= approved_face_threshold()
                except (TypeError, ValueError):
                    score_ok = False
                if status != "passed" or not score_ok:
                    blocked.append("face_review:score_below_approved_threshold")

    if missing or incomplete or blocked or no_artifact:
        parts = []
        if missing:
            parts.append(f"missing_nodes={missing}")
        if incomplete:
            parts.append(f"incomplete={incomplete}")
        if no_artifact:
            parts.append(f"no_artifact={no_artifact}")
        if blocked:
            parts.append(f"blocked_review={blocked}")
        raise ValidationAppError("APPROVE_GATE: " + "; ".join(parts))


async def _has_manual_artifact(
    session: AsyncSession, *, project_id: UUID, shot_id: UUID, node_key: str
) -> bool:
    arts = list(
        (
            await session.execute(
                select(Artifact).where(
                    Artifact.project_id == project_id,
                    Artifact.storage_state == "available",
                )
            )
        )
        .scalars()
        .all()
    )
    needle = f"shot={shot_id}"
    node_needle = f"node={node_key}"
    for a in arts:
        reason = a.delete_reason or ""
        if "audited_manual_upload" in reason and needle in reason and node_needle in reason:
            return True
        if str(shot_id) in a.object_key and node_key in a.object_key:
            return True
    return False


async def approve_shot(
    session: AsyncSession,
    *,
    project_id: UUID,
    shot_id: UUID,
    user_id: UUID,
    note: str = "",
) -> ShotReviewResult:
    shot = await get_shot_or_404(session, project_id=project_id, shot_id=shot_id)
    if await is_shot_locked(session, project_id=project_id, shot_id=shot_id):
        raise ValidationAppError("shot is human-locked; unlock before approve")
    await assert_shot_approvable(session, project_id=project_id, shot_id=shot_id)
    shot.status = "review_passed"
    shot.version = int(getattr(shot, "version", 1) or 1) + 1
    await session.flush()
    audit = f"approved by={user_id}"
    if note.strip():
        audit = f"{audit} note={note.strip()[:120]}"
    return ShotReviewResult(
        shot_id=shot_id,
        status=shot.status,
        locked=False,
        message=audit,
    )


async def reject_shot(
    session: AsyncSession,
    *,
    project_id: UUID,
    shot_id: UUID,
    user_id: UUID,
    reason: str,
) -> ShotReviewResult:
    shot = await get_shot_or_404(session, project_id=project_id, shot_id=shot_id)
    if await is_shot_locked(session, project_id=project_id, shot_id=shot_id):
        raise ValidationAppError("shot is human-locked; unlock before reject")
    if not reason.strip():
        raise ValidationAppError("reject reason required")
    shot.status = "review_rejected"
    await session.flush()
    return ShotReviewResult(
        shot_id=shot_id,
        status=shot.status,
        locked=False,
        message=f"rejected by={user_id} reason={reason[:200]}",
    )


async def lock_shot(
    session: AsyncSession,
    *,
    project_id: UUID,
    shot_id: UUID,
    user_id: UUID,
    locked: bool,
) -> ShotReviewResult:
    await get_shot_or_404(session, project_id=project_id, shot_id=shot_id)
    row = await set_shot_lock(
        session, project_id=project_id, shot_id=shot_id, user_id=user_id, locked=locked
    )
    return ShotReviewResult(
        shot_id=shot_id,
        status="locked" if locked else "unlocked",
        locked=row.locked,
        message="human lock set" if locked else "human lock cleared",
    )


async def start_shot_nodes(
    session: AsyncSession,
    *,
    project_id: UUID,
    shot_id: UUID,
    user_id: UUID,
    node_keys: list[str] | None = None,
    force: bool = False,
) -> list[UUID]:
    """Queue missing shot-pipeline nodes with persisted Plan and Shot context.

    A normal start is idempotent: already queued or successful nodes are left
    alone. Local re-runs set ``force`` so they create a new attempt only for
    the invalidated nodes.
    """
    if await is_shot_locked(session, project_id=project_id, shot_id=shot_id):
        raise ValidationAppError("shot is human-locked")
    keys = node_keys or list(SHOT_NODES)
    for k in keys:
        if k not in SHOT_NODES:
            raise ValidationAppError(f"unknown node key: {k}")

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
    latest_by_key = _latest_by_node_key(_shot_runs(existing_runs, shot_id))
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
    if not canonical_binding:
        from app.assets.models import Asset, Character, CharacterReference

        canonical = (
            await session.execute(
                select(CharacterReference, Character.locked_prompt, Artifact)
                .join(Character, Character.id == CharacterReference.character_id)
                .join(Asset, Asset.id == Character.id)
                .outerjoin(Artifact, Artifact.id == CharacterReference.artifact_id)
                .where(Asset.project_id == project_id)
                .where(CharacterReference.is_canonical.is_(True))
                .order_by(CharacterReference.created_at.desc(), CharacterReference.id.desc())
                .limit(1)
            )
        ).one_or_none()
        if canonical is not None:
            reference, locked_prompt, artifact = canonical
            if artifact is not None and reference.artifact_id is not None:
                canonical_binding = {
                    "canonical_artifact_id": str(artifact.id),
                    "canonical_object_key": artifact.object_key,
                    "canonical_content_hash": artifact.content_hash,
                    "canonical_mime_type": artifact.mime_type,
                }
            if isinstance(locked_prompt, str):
                canonical_locked_prompt = locked_prompt
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
        lead_identity_required = shot_plan.get("lead_identity_required") is True
        # A project with a registered lead canonical is single-lead in P0. Script
        # imports carry no per-shot lead flag, so default lead shots to identity
        # required when a canonical exists (face gate applies).
        if not lead_identity_required and canonical_binding:
            lead_identity_required = True
        if key == "keyframe" and lead_identity_required and canonical_locked_prompt:
            prompt = identity_priority_keyframe_prompt(
                prompt,
                canonical_locked_prompt=canonical_locked_prompt,
            )
        model_profile: dict[str, object] = {}
        if key in {"keyframe", "video", "voice"}:
            from app.providers.model_profiles.node_snapshot import (
                planned_node_model_profile,
            )

            model_profile = await planned_node_model_profile(
                session, project=project, node_key=key
            )
        snapshot: dict[str, object] = {
            "shot_id": str(shot_id),
            "node_key": key,
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
            "subtitle": dialogue,
            "lead_identity_required": lead_identity_required,
            "face_policy": approved_face_policy_snapshot(),
            "model_profile": model_profile,
        }
        snapshot.update(canonical_binding)
        if canonical_locked_prompt:
            snapshot["canonical_locked_prompt"] = canonical_locked_prompt
        if key == "face_review":
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


async def local_rerun_from_node(
    session: AsyncSession,
    *,
    project_id: UUID,
    shot_id: UUID,
    user_id: UUID,
    changed_node_key: str,
) -> tuple[list[str], list[UUID]]:
    """Mark correct downstream stale and return (keys, run_ids) that must re-run."""
    if await is_shot_locked(session, project_id=project_id, shot_id=shot_id):
        raise ValidationAppError("shot is human-locked")
    if changed_node_key not in SHOT_NODES:
        raise ValidationAppError(f"unknown node: {changed_node_key}")
    stale = mark_stale_downstream(
        changed_node_key=changed_node_key,
        node_keys=list(SHOT_NODES),
        edges=SHOT_EDGES,
    )
    # Include the changed node itself
    to_run = [changed_node_key] + [k for k in stale if k != changed_node_key]
    run_ids = await start_shot_nodes(
        session,
        project_id=project_id,
        shot_id=shot_id,
        user_id=user_id,
        node_keys=to_run,
        force=True,
    )
    return to_run, run_ids


async def upload_manual_media(
    session: AsyncSession,
    *,
    project_id: UUID,
    shot_id: UUID,
    user_id: UUID,
    node_key: str,
    data: bytes,
    mime_type: str,
    note: str = "",
    store: ObjectStore | None = None,
) -> Artifact:
    """Audited manual media as immutable Artifact + completed NodeRun (zero Provider cost).

    Completes the registered shot-p0-v1 node so approve/export gates see real
    Graph lineage without BYOK Provider calls.
    """
    from datetime import UTC, datetime

    from app.production.models import ProductionGraph
    from app.production.service import GraphService

    if not data:
        raise ValidationAppError("empty media bytes")
    if node_key not in SHOT_NODES:
        raise ValidationAppError(f"unknown node: {node_key}")
    if await is_shot_locked(session, project_id=project_id, shot_id=shot_id):
        raise ValidationAppError("shot is human-locked")
    await get_shot_or_404(session, project_id=project_id, shot_id=shot_id)
    obj = store or get_object_store()
    content_hash = hashlib.sha256(data).hexdigest()
    object_key = f"projects/{project_id}/manual/{shot_id}/{node_key}/{content_hash[:16]}"
    stored = await obj.put_bytes(object_key=object_key, data=data, mime_type=mime_type)
    # Map to frozen artifact_type enum (image/video/audio/document/…)
    if mime_type.startswith("video/"):
        art_type = "video"
    elif mime_type.startswith("audio/"):
        art_type = "audio"
    elif mime_type.startswith("image/") or mime_type == "application/octet-stream":
        art_type = "image"
    else:
        art_type = "document"
    note_safe = (note or "").strip().replace("\n", " ")[:80]
    audit = (f"audited_manual_upload shot={shot_id} node={node_key} by={user_id} note={note_safe}")[
        :240
    ]

    # Ensure shot graph + node exist, then complete a NodeRun linked to Artifact.
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
    if existing is None or existing.current_version_id is None:
        graph = await graphs.create_graph(
            project_id=project_id,
            scope_type="shot",
            scope_entity_id=shot_id,
            template_key=SHOT_PIPELINE_TEMPLATE_KEY,
            created_by=user_id,
            definition=shot_pipeline_definition(),
        )
    else:
        graph = existing
    assert graph.current_version_id is not None
    version_id = graph.current_version_id
    materialized = await graphs.materialize_definition(version_id=version_id)
    if materialized.version.status == "draft":
        await graphs.publish(version_id=version_id, published_by=user_id)
    node = materialized.nodes[node_key]
    prior = list(
        (
            await session.execute(
                select(NodeRun).where(
                    NodeRun.project_id == project_id,
                    NodeRun.graph_node_id == node.id,
                )
            )
        )
        .scalars()
        .all()
    )
    now = datetime.now(UTC)
    ih = hashlib.sha256(f"manual:{shot_id}:{node_key}:{content_hash}".encode()).hexdigest()
    run = NodeRun(
        project_id=project_id,
        graph_version_id=version_id,
        graph_node_id=node.id,
        attempt_no=len(prior) + 1,
        idempotency_key=f"manual:{node_key}:{shot_id}:{content_hash[:16]}",
        input_hash=ih,
        status="queued",
        input_snapshot={
            "shot_id": str(shot_id),
            "node_key": node_key,
            "source_commit": get_settings().source_commit,
            "manual": True,
            "prompt": f"manual:{node_key}:{shot_id}",
            "face_policy": approved_face_policy_snapshot(),
        },
        provider_cost=Decimal("0"),
        started_at=now,
        created_by=user_id,
    )
    session.add(run)
    await session.flush()
    art = await get_or_create_artifact(
        session,
        project_id=project_id,
        artifact_type=art_type,
        object_key=stored.object_key,
        content_hash=stored.content_hash,
        mime_type=mime_type,
        byte_size=stored.byte_size,
        produced_by_run_id=run.id,
    )
    if not art.delete_reason:
        art.delete_reason = audit
    run.status = "completed"
    run.finished_at = now
    run.result_artifact_id = art.id
    run.output_summary = {
        "status": "passed",
        "manual": True,
        "audit": audit,
        "zero_provider_cost": True,
        "artifact_id": str(art.id),
        "content_hash": art.content_hash,
        "byte_size": art.byte_size,
    }
    node.latest_successful_run_id = run.id
    shot = await get_shot_or_404(session, project_id=project_id, shot_id=shot_id)
    if shot.status in {"draft", "pending", "review_rejected"}:
        shot.status = "in_production"
    await session.flush()
    return art


async def shot_status_summary(
    session: AsyncSession, *, project_id: UUID, shot_id: UUID
) -> dict[str, object]:
    await get_shot_or_404(session, project_id=project_id, shot_id=shot_id)
    locked = await is_shot_locked(session, project_id=project_id, shot_id=shot_id)
    runs = list(
        (
            await session.execute(
                select(NodeRun)
                .where(NodeRun.project_id == project_id)
                .order_by(NodeRun.created_at.desc())
                .limit(200)
            )
        )
        .scalars()
        .all()
    )
    shot_runs = _shot_runs(runs, shot_id)
    failed = [r for r in shot_runs if r.status == "failed"]
    guidance = None
    if failed:
        fr = failed[0]
        code = fr.error_code or "UNKNOWN"
        guidance = {
            "error_code": code,
            "summary": fr.error_summary,
            "retry_suggestion": _retry_suggestion(code),
        }
    shot = await session.get(Shot, shot_id)
    return {
        "shot_id": str(shot_id),
        "status": shot.status if shot else "unknown",
        "locked": locked,
        "node_run_count": len(shot_runs),
        "failed_count": len(failed),
        "guidance": guidance,
        "pipeline": list(SHOT_NODES),
    }


def _retry_suggestion(code: str) -> str:
    mapping = {
        "PROVIDER_NOT_CONFIGURED": "配置 BYOK Provider 或使用受审计手工媒体上传",
        "MODEL_BINDING_NOT_VERIFIED": (
            "完成 documented、contract_tested、account_verified、quality_gated 四层证据"
        ),
        "CANONICAL_REFERENCE_REQUIRED": "先注册主角 canonical Reference",
        "UPSTREAM_RUN_MISSING": "检查同 Shot、同 GraphVersion、同 attempt 的上游 NodeRun",
        "UPSTREAM_TERMINAL_FAILURE": "先处理首个上游失败节点，再从该节点及真实下游局部重跑",
        "UPSTREAM_ARTIFACT_MISSING": "核对上游 Run、Artifact、对象存储状态和 content hash",
        "PROVIDER_TASK_PENDING": "保留远端任务 ID，恢复 Worker 后继续 Poll，不重新创建任务",
        "PROVIDER_SUBMISSION_UNKNOWN": "人工核对 Provider 任务和账单后再决定是否创建新 attempt",
        "PROVIDER_CREATE_FAILED": "检查脱敏 Provider 错误和请求合同，只重试当前创建节点",
        "PROVIDER_TASK_FAILED": "检查远端任务错误；确认后只重跑当前 Provider 节点及下游",
        "PROVIDER_MEDIA_DOWNLOAD_FAILED": "续查同一远端任务或结果 URL，修复下载后再入库",
        "FACE_BELOW_THRESHOLD": "保持 0.60 阈值，从 Keyframe 返工，最多使用批准的有限次数",
        "FACE_PROBE_UNAVAILABLE": "检查两源 Artifact、InsightFace 和画面清晰度后进入人工复核",
        "VIDEO_DRIFT_BLOCKED": "查看抽样时间点和分数，从 Video 及下游重跑",
        "VIDEO_DRIFT_POLICY_UNAPPROVED": "Video Drift 未通过（均值 < 0.40）阻断交付",
        "blocked_budget": "增加或调整项目预算后重试原节点，不创建 ProviderOperation",
        "PROVIDER_FAILED": "检查 Provider 状态后重试该节点及正确下游",
        "QUEUE_UNAVAILABLE": "启动 Redis 与 Arq Worker 后 dispatch/enqueue",
        "APPROVE_GATE": "先完成必需节点与 face/continuity 审核",
    }
    return mapping.get(code, "查看 NodeRun error_summary 后局部重跑失败节点")
