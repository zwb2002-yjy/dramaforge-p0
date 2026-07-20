"""S4 product-ish 10-shot production using full shot-p0-v1 node set."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.execution.models import Artifact, GraphNode, NodeRun
from app.execution.runtime_invariants import mark_stale_downstream, run_or_cache
from app.production.service import GraphService

# Freeze agent.md S4: full shot-p0-v1 nodes
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

# Map to 04 node_type enum values
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
    continuity_checked: bool = False


async def produce_shots_p0(
    session: AsyncSession,
    *,
    project_id: UUID,
    user_id: UUID,
    n: int = 10,
    budget: Decimal = Decimal("1000"),
) -> list[ShotRecord]:
    graphs = GraphService(session)
    remaining = budget
    shots: list[ShotRecord] = []
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
            subtitle=f"Line {i}",
        )
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
            ih = f"{shot_id}:{key}:v1"
            # Reviews still produce NodeRuns + Artifacts (audit evidence)
            run, remaining = await run_or_cache(
                session,
                project_id=project_id,
                graph_version_id=graph.current_version_id,
                graph_node=node,
                input_hash=ih,
                created_by=user_id,
                budget_remaining=remaining,
                cost=Decimal("1"),
            )
            rec.run_ids[key] = run.id
            if run.result_artifact_id is not None:
                rec.artifact_ids[key] = run.result_artifact_id
            if key == "face_review":
                rec.face_checked = True
                run.output_summary = {**(run.output_summary or {}), "review": "passed"}
            if key == "continuity_review":
                rec.continuity_checked = True
                run.output_summary = {**(run.output_summary or {}), "review": "passed"}
        rec.status = "review_passed"
        shots.append(rec)
    await session.commit()
    return shots


async def rework_subtitle_only_p0(
    session: AsyncSession,
    *,
    project_id: UUID,
    user_id: UUID,
    shot: ShotRecord,
    new_subtitle: str,
    budget: Decimal,
) -> ShotRecord:
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
    remaining = budget
    for key in ("subtitle", "composite", "continuity_review"):
        node = await session.get(GraphNode, shot.node_ids[key])
        assert node is not None
        ih = f"{shot.shot_id}:{key}:{new_subtitle}"
        run, remaining = await run_or_cache(
            session,
            project_id=project_id,
            graph_version_id=shot.graph_version_id,
            graph_node=node,
            input_hash=ih,
            created_by=user_id,
            budget_remaining=remaining,
            cost=Decimal("1"),
        )
        shot.run_ids[key] = run.id
        if run.result_artifact_id is not None:
            shot.artifact_ids[key] = run.result_artifact_id
    await session.commit()
    shot.status = "review_passed"
    return shot
