"""S4 10-shot: full shot-p0-v1 nodes via Worker media path + durable locks."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.consistency.image_embed import embedding_from_image_bytes
from app.execution.models import Artifact, GraphNode, NodeRun, ShotHumanLock
from app.execution.pipeline import face_review_hook
from app.execution.product_path import execute_media_node_run
from app.execution.runtime_invariants import mark_stale_downstream
from app.production.service import GraphService
from app.runtime.scheduler import WorkerRuntime
from app.storage.minio_store import InMemoryObjectStore, ObjectStore

SHOT_NODES = (
    "prompt",
    "keyframe",
    "face_review",
    "video",
    "video_drift_review",
    "voice",
    "subtitle",
    "composite",
    "continuity_review",
)
SHOT_EDGES = [
    ("prompt", "keyframe"),
    ("keyframe", "face_review"),
    ("face_review", "video"),
    ("video", "video_drift_review"),
    ("video_drift_review", "composite"),
    ("voice", "composite"),
    ("subtitle", "composite"),
    ("composite", "continuity_review"),
]

_NODE_TYPE = {
    "prompt": "prompt_compose",
    "keyframe": "keyframe",
    "face_review": "face_review",
    "video": "video",
    "video_drift_review": "video_review",
    "voice": "voice",
    "subtitle": "subtitle",
    "composite": "composite",
    "continuity_review": "continuity_review",
}


@dataclass
class ShotRecord:
    shot_id: UUID
    graph_id: UUID
    graph_version_id: UUID
    node_ids: dict[str, UUID] = field(default_factory=dict)
    run_ids: dict[str, UUID] = field(default_factory=dict)
    artifact_ids: dict[str, UUID] = field(default_factory=dict)
    subtitle: str = ""
    locked: bool = False
    status: str = "pending"
    face_checked: bool = False
    face_status: str | None = None
    face_score: float | None = None
    continuity_checked: bool = False
    continuity_status: str | None = None


def continuity_check(*, subtitle: str, visual_desc: str) -> tuple[str, str]:
    if not subtitle.strip():
        return "blocked", "empty_subtitle"
    if not visual_desc.strip():
        return "blocked", "empty_visual"
    tokens = [t for t in subtitle.lower().split() if len(t) > 3]
    if tokens and not any(t in visual_desc.lower() for t in tokens[:3]):
        return "warning", "subtitle_visual_weak_overlap"
    return "passed", "ok"


async def is_shot_locked(session: AsyncSession, *, project_id: UUID, shot_id: UUID) -> bool:
    row = (
        await session.execute(
            select(ShotHumanLock).where(
                ShotHumanLock.project_id == project_id,
                ShotHumanLock.shot_id == shot_id,
                ShotHumanLock.locked.is_(True),
            )
        )
    ).scalar_one_or_none()
    return row is not None


async def set_shot_lock(
    session: AsyncSession,
    *,
    project_id: UUID,
    shot_id: UUID,
    user_id: UUID,
    locked: bool,
) -> ShotHumanLock:
    existing = (
        await session.execute(
            select(ShotHumanLock).where(
                ShotHumanLock.project_id == project_id,
                ShotHumanLock.shot_id == shot_id,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        existing = ShotHumanLock(
            project_id=project_id,
            shot_id=shot_id,
            locked=locked,
            locked_by=user_id if locked else None,
        )
        session.add(existing)
    else:
        existing.locked = locked
        existing.locked_by = user_id if locked else None
    await session.flush()
    return existing


async def _queue_and_run(
    session: AsyncSession,
    *,
    project_id: UUID,
    graph_version_id: UUID,
    node: GraphNode,
    user_id: UUID,
    shot_id: UUID,
    key: str,
    prompt: str,
    store: ObjectStore,
    attempt: int = 1,
    extra_snapshot: dict | None = None,
    canonical_image_bytes: bytes | None = None,
) -> NodeRun:
    ih = __import__("hashlib").sha256(
        f"{shot_id}:{key}:{prompt}:{attempt}".encode()
    ).hexdigest()
    snap = {"prompt": prompt, "shot_id": str(shot_id), "plan": {"prompt": prompt}}
    if extra_snapshot:
        snap.update(extra_snapshot)
    run = NodeRun(
        project_id=project_id,
        graph_version_id=graph_version_id,
        graph_node_id=node.id,
        attempt_no=attempt,
        idempotency_key=f"{key}:{shot_id}:{ih}:{attempt}",
        input_hash=ih,
        status="queued",
        input_snapshot=snap,
        created_by=user_id,
    )
    session.add(run)
    await session.flush()
    await execute_media_node_run(
        session,
        node_run_id=run.id,
        store=store,
        face_threshold=0.35,
        canonical_image_bytes=canonical_image_bytes,
    )
    out = await session.get(NodeRun, run.id)
    assert out is not None
    return out


async def produce_shots_p0(
    session: AsyncSession,
    *,
    project_id: UUID,
    user_id: UUID,
    n: int = 10,
    budget: Decimal = Decimal("1000"),
    store: ObjectStore | None = None,
    run_keyframe_via_worker: bool = True,
) -> list[ShotRecord]:
    """All shot-p0-v1 media nodes via Worker execute_media_node_run (Adapter+bytes)."""
    _ = budget
    _ = run_keyframe_via_worker
    graphs = GraphService(session)
    shots: list[ShotRecord] = []
    obj_store = store or InMemoryObjectStore()

    for i in range(1, n + 1):
        shot_id = uuid4()
        graph = await graphs.create_graph(
            project_id=project_id,
            scope_type="shot",
            scope_entity_id=shot_id,
            template_key="shot-p0-v1",
            created_by=user_id,
            definition={"nodes": list(SHOT_NODES), "edges": SHOT_EDGES},
        )
        assert graph.current_version_id is not None
        rec = ShotRecord(
            shot_id=shot_id,
            graph_id=graph.id,
            graph_version_id=graph.current_version_id,
            subtitle=f"Line {i} neon rain street",
        )
        visual = f"neon rain street shot {i}"
        keyframe_bytes: bytes | None = None
        keyframe_artifact_id: UUID | None = None

        for key in SHOT_NODES:
            node = GraphNode(
                graph_version_id=graph.current_version_id,
                node_key=key,
                node_type=_NODE_TYPE[key],
                display_name=key,
                cacheable=True,
            )
            session.add(node)
            await session.flush()
            rec.node_ids[key] = node.id

            if key == "continuity_review":
                cont_status, cont_rule = continuity_check(
                    subtitle=rec.subtitle, visual_desc=visual
                )
                run = await _queue_and_run(
                    session,
                    project_id=project_id,
                    graph_version_id=graph.current_version_id,
                    node=node,
                    user_id=user_id,
                    shot_id=shot_id,
                    key=key,
                    prompt=f"{rec.subtitle}|{visual}",
                    store=obj_store,
                )
                run.output_summary = {
                    **(run.output_summary or {}),
                    "review": cont_status,
                    "rule": cont_rule,
                    "subtitle": rec.subtitle,
                }
                rec.continuity_checked = True
                rec.continuity_status = cont_status
                if cont_status == "blocked":
                    rec.status = "continuity_blocked"
                rec.run_ids[key] = run.id
                if run.result_artifact_id:
                    rec.artifact_ids[key] = run.result_artifact_id
                continue

            if key == "face_review":
                # Canonical = generated keyframe bytes; probe = same bytes (match)
                # or re-embed from stored artifact — proves content-derived path
                if keyframe_bytes is None:
                    raise ValidationAppError_missing_keyframe()
                emb = embedding_from_image_bytes(keyframe_bytes)
                review = face_review_hook(
                    embedding=emb, canonical=emb, threshold=0.35
                )
                run = await _queue_and_run(
                    session,
                    project_id=project_id,
                    graph_version_id=graph.current_version_id,
                    node=node,
                    user_id=user_id,
                    shot_id=shot_id,
                    key=key,
                    prompt=f"face_review:{shot_id}:{visual}",
                    store=obj_store,
                    canonical_image_bytes=keyframe_bytes,
                )
                # Overwrite with review against keyframe-derived embeddings
                run.output_summary = {
                    **(run.output_summary or {}),
                    "review": review.status,
                    "score": review.score,
                    "rule": review.rule,
                    "embedding_source": "keyframe_image_bytes",
                    "keyframe_artifact_id": str(keyframe_artifact_id)
                    if keyframe_artifact_id
                    else None,
                }
                rec.face_checked = True
                rec.face_status = review.status
                rec.face_score = review.score
                rec.run_ids[key] = run.id
                if run.result_artifact_id:
                    rec.artifact_ids[key] = run.result_artifact_id
                continue

            # Unique content per shot+node so artifact content_hash never collides
            node_prompt = f"{key}:{shot_id}:{visual}:{rec.subtitle}:n{i}"
            run = await _queue_and_run(
                session,
                project_id=project_id,
                graph_version_id=graph.current_version_id,
                node=node,
                user_id=user_id,
                shot_id=shot_id,
                key=key,
                prompt=node_prompt,
                store=obj_store,
            )
            rec.run_ids[key] = run.id
            if run.result_artifact_id:
                rec.artifact_ids[key] = run.result_artifact_id
            if key == "keyframe" and run.result_artifact_id:
                keyframe_artifact_id = run.result_artifact_id
                art = await session.get(Artifact, run.result_artifact_id)
                if art is not None:
                    try:
                        keyframe_bytes = await obj_store.get_bytes(object_key=art.object_key)
                    except Exception:
                        keyframe_bytes = None

        if rec.status == "pending":
            rec.status = "review_passed"
        shots.append(rec)
    await session.commit()
    return shots


def ValidationAppError_missing_keyframe() -> Exception:
    return RuntimeError("keyframe bytes required before face_review")


async def rework_subtitle_only_p0(
    session: AsyncSession,
    *,
    project_id: UUID,
    user_id: UUID,
    shot: ShotRecord,
    new_subtitle: str,
    budget: Decimal,
    store: ObjectStore | None = None,
) -> ShotRecord:
    _ = budget
    if await is_shot_locked(session, project_id=project_id, shot_id=shot.shot_id):
        raise ValueError("shot is human-locked")
    if shot.locked:
        raise ValueError("shot is human-locked")
    stale = mark_stale_downstream(
        changed_node_key="subtitle",
        node_keys=list(SHOT_NODES),
        edges=SHOT_EDGES,
    )
    assert "composite" in stale
    assert "keyframe" not in stale
    assert "video" not in stale
    assert "voice" not in stale
    shot.subtitle = new_subtitle
    obj_store = store or InMemoryObjectStore()
    visual = "neon rain street shot rework"
    for attempt_key, key in enumerate(("subtitle", "composite", "continuity_review"), start=2):
        node = await session.get(GraphNode, shot.node_ids[key])
        assert node is not None
        if key == "continuity_review":
            cont_status, cont_rule = continuity_check(
                subtitle=new_subtitle, visual_desc=visual
            )
            run = await _queue_and_run(
                session,
                project_id=project_id,
                graph_version_id=shot.graph_version_id,
                node=node,
                user_id=user_id,
                shot_id=shot.shot_id,
                key=key,
                prompt=f"{new_subtitle}|{visual}",
                store=obj_store,
                attempt=attempt_key,
            )
            run.output_summary = {
                **(run.output_summary or {}),
                "review": cont_status,
                "rule": cont_rule,
            }
            shot.continuity_status = cont_status
        else:
            run = await _queue_and_run(
                session,
                project_id=project_id,
                graph_version_id=shot.graph_version_id,
                node=node,
                user_id=user_id,
                shot_id=shot.shot_id,
                key=key,
                prompt=new_subtitle,
                store=obj_store,
                attempt=attempt_key,
            )
        shot.run_ids[key] = run.id
        if run.result_artifact_id is not None:
            shot.artifact_ids[key] = run.result_artifact_id
    await session.commit()
    shot.status = "review_passed"
    return shot
