"""Batch read projection for the storyboard; never writes Shot or execution state."""

from __future__ import annotations

from collections import defaultdict
from typing import TypedDict
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Shot
from app.delivery.models import HumanReviewDecision
from app.execution.models import Artifact, GraphNode, NodeRun
from app.production.formal_selection import list_candidate_facts
from app.production.models import GraphVersion, ProductionGraph
from app.production.review_gate import latest_review_decision, subject_fingerprint
from app.production.trace_query import load_unknown_submission_run_ids


class ShotOverviewFacts(TypedDict):
    pending_review: bool
    generating: bool
    generation_failed: bool
    outcome_unknown: bool


async def load_shot_overview(
    session: AsyncSession,
    *,
    project_id: UUID,
    shots: list[Shot],
    candidate_admissions: dict[UUID, list[dict[str, object]]] | None = None,
) -> dict[UUID, ShotOverviewFacts]:
    result: dict[UUID, ShotOverviewFacts] = {
        shot.id: {
            "pending_review": False,
            "generating": False,
            "generation_failed": False,
            "outcome_unknown": False,
        }
        for shot in shots
    }
    if not shots:
        return result
    shot_by_id = {shot.id: shot for shot in shots}
    ranked = (
        select(
            NodeRun.id.label("run_id"),
            ProductionGraph.scope_entity_id.label("shot_id"),
            func.row_number()
            .over(
                partition_by=(ProductionGraph.scope_entity_id, GraphNode.node_key),
                order_by=(NodeRun.created_at.desc(), NodeRun.attempt_no.desc(), NodeRun.id.desc()),
            )
            .label("rank"),
        )
        .join(GraphNode, GraphNode.id == NodeRun.graph_node_id)
        .join(GraphVersion, GraphVersion.id == GraphNode.graph_version_id)
        .join(ProductionGraph, ProductionGraph.id == GraphVersion.graph_id)
        .where(
            NodeRun.project_id == project_id,
            ProductionGraph.project_id == project_id,
            ProductionGraph.scope_type == "shot",
            ProductionGraph.scope_entity_id.in_(shot_by_id),
            NodeRun.graph_version_id == GraphNode.graph_version_id,
            GraphNode.node_key.in_(("keyframe", "video")),
        )
        .subquery()
    )
    latest = (
        await session.execute(
            select(NodeRun, ranked.c.shot_id)
            .join(ranked, ranked.c.run_id == NodeRun.id)
            .where(ranked.c.rank == 1)
        )
    ).all()
    unknown = await load_unknown_submission_run_ids(
        session, run_ids=[run.id for run, _shot_id in latest]
    )
    for run, shot_id in latest:
        if run.id in unknown:
            result[shot_id]["outcome_unknown"] = True
        elif run.status in {"queued", "running", "cancel_requested"}:
            result[shot_id]["generating"] = True
        elif run.status in {"failed", "blocked"}:
            result[shot_id]["generation_failed"] = True

    candidates = (
        candidate_admissions
        if candidate_admissions is not None
        else await list_candidate_facts(session, project_id=project_id, shot_ids=list(shot_by_id))
    )
    judged: set[tuple[UUID, str]] = set()
    if candidate_admissions is None:
        artifact_ids = {
            UUID(str(candidate["artifact_id"]))
            for rows in candidates.values()
            for candidate in rows
        }
        groups: dict[tuple[UUID, str], list[HumanReviewDecision]] = defaultdict(list)
        if artifact_ids:
            decisions = (
                await session.scalars(
                    select(HumanReviewDecision).where(
                        HumanReviewDecision.project_id == project_id,
                        HumanReviewDecision.artifact_id.in_(artifact_ids),
                        HumanReviewDecision.review_kind.in_(("identity", "video_drift")),
                    )
                )
            ).all()
            for decision in decisions:
                groups[(decision.artifact_id, decision.review_kind)].append(decision)
        heads = [
            head for rows in groups.values() if (head := latest_review_decision(rows)) is not None
        ]
        evidence_ids = {head.review_artifact_id for head in heads if head.decision == "approved"}
        evidence = (
            {
                artifact.id: artifact
                for artifact in (
                    await session.scalars(
                        select(Artifact).where(
                            Artifact.project_id == project_id, Artifact.id.in_(evidence_ids)
                        )
                    )
                ).all()
            }
            if evidence_ids
            else {}
        )
        hashes = {
            UUID(str(candidate["artifact_id"])): str(candidate["content_hash"])
            for rows in candidates.values()
            for candidate in rows
        }
        for decision in heads:
            if decision.decision == "rejected":
                judged.add((decision.artifact_id, decision.review_kind))
            elif decision.decision == "approved":
                proof = evidence.get(decision.review_artifact_id)
                expected = subject_fingerprint(
                    artifact_id=decision.artifact_id,
                    artifact_content_hash=hashes[decision.artifact_id],
                    review_kind=decision.review_kind,
                    review_node_run_id=decision.review_node_run_id,
                    review_artifact_id=decision.review_artifact_id,
                    review_evidence_hash=proof.content_hash if proof is not None else None,
                )
                if decision.subject_fingerprint == expected:
                    judged.add((decision.artifact_id, decision.review_kind))
    for shot_id, rows in candidates.items():
        shot = shot_by_id[shot_id]
        for candidate in rows:
            if "artifact_id" not in candidate or candidate.get("stage") not in {
                "image_keyframe",
                "video",
            }:
                continue
            artifact_id = UUID(str(candidate["artifact_id"]))
            if artifact_id in {shot.formal_keyframe_artifact_id, shot.formal_video_artifact_id}:
                continue
            if candidate_admissions is not None:
                decided = (
                    candidate.get("review_allowed") is True
                    or candidate.get("review_decision") == "rejected"
                )
            else:
                kind = "identity" if candidate["stage"] == "image_keyframe" else "video_drift"
                decided = (artifact_id, kind) in judged
            if not decided:
                result[shot_id]["pending_review"] = True
    return result
