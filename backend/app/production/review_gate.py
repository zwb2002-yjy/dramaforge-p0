"""Human review decisions and the production admission they authorize.

A stored review NodeRun proves a machine check ran; it never proves a person
accepted the picture. This module records the human judgement and answers, for
one Artifact, whether the production chain may continue.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.delivery.models import HumanReviewDecision
from app.execution.models import Artifact, GraphNode, NodeRun
from app.shared.errors import ConflictError, ValidationAppError

ReviewKind = Literal["identity", "video_drift", "continuity"]
ReviewDecision = Literal["approved", "rejected", "demo_confirmed"]

# Review NodeRun node keys, in the vocabulary of the canonical shot pipeline.
REVIEW_NODE_KEYS: dict[ReviewKind, str] = {
    "identity": "identity_review",
    "video_drift": "video_drift_review",
    "continuity": "continuity_review",
}

# Which review decides admission for which stage of the chain.
STAGE_REVIEW_KIND: dict[str, ReviewKind] = {
    "formal_keyframe": "identity",
    "formal_video": "video_drift",
    "delivery": "continuity",
}

# Review results that describe a machine outcome rather than a person's call.
_OUTCOME_UNKNOWN_STATUSES = frozenset({"needs_human", "blocked", "failed"})


def review_request_hash(
    *,
    artifact_id: UUID,
    review_node_run_id: UUID,
    review_kind: str,
    decision: str,
    reason: str,
    shot_version: int,
) -> str:
    """Canonical identity of one decision submission (retry-safe)."""
    canonical = json.dumps(
        {
            "artifact_id": str(artifact_id),
            "review_node_run_id": str(review_node_run_id),
            "review_kind": review_kind,
            "decision": decision,
            "reason": reason,
            "shot_version": shot_version,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def judgement_fingerprint(
    *,
    artifact_id: UUID,
    review_kind: str,
    decision: str,
    reason: str,
) -> str:
    """The judgement a person expressed, independent of when they expressed it.

    ``review_request_hash`` additionally binds the review run and the Shot
    version, so it changes when the Shot moves on (for example after a Formal
    selection) even though the person's verdict and words are unchanged.  That
    makes it the wrong key for deciding whether a submission is a new decision.
    """

    canonical = json.dumps(
        {
            "artifact_id": str(artifact_id),
            "review_kind": review_kind,
            "decision": decision,
            "reason": reason,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def subject_fingerprint(
    *,
    artifact_id: UUID,
    artifact_content_hash: str,
    review_kind: str,
    review_node_run_id: UUID,
    review_artifact_id: UUID,
    review_evidence_hash: str | None,
) -> str:
    """What this decision is about.

    Bound to the media bytes, the review kind and the review evidence — but not
    to the Shot version or the Formal pointer, so confirming a Formal selection
    cannot invalidate the decision that authorized it.
    """
    canonical = json.dumps(
        {
            "artifact_id": str(artifact_id),
            "artifact_content_hash": artifact_content_hash,
            "review_kind": review_kind,
            "review_node_run_id": str(review_node_run_id),
            "review_artifact_id": str(review_artifact_id),
            "review_evidence_hash": review_evidence_hash or "",
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ReviewRequirement:
    """One review kind that a stage needs, and what the facts say about it."""

    review_kind: ReviewKind
    node_key: str
    review_node_run_id: UUID | None
    review_artifact_id: UUID | None
    machine_status: str | None
    decision: str | None
    decision_reason: str | None
    applies: bool
    blocked_reason: str | None
    decision_id: UUID | None = None


@dataclass(frozen=True)
class StageAdmission:
    """Admission answer for one production stage of one Artifact."""

    allowed: bool
    review_kind: ReviewKind | None = None
    requirements: list[ReviewRequirement] = field(default_factory=list)

    @property
    def blocker(self) -> str | None:
        for requirement in self.requirements:
            if requirement.blocked_reason:
                return requirement.blocked_reason
        return None

    @property
    def blocked_reason_codes(self) -> list[str]:
        return [r.blocked_reason for r in self.requirements if r.blocked_reason]


async def _latest_decision(
    session: AsyncSession,
    *,
    project_id: UUID,
    artifact_id: UUID,
    review_kind: ReviewKind,
) -> HumanReviewDecision | None:
    """The decision that currently governs this Artifact.

    Ordering is by ``supersedes_id`` rather than by timestamp: two decisions
    written in the same transaction can share a timestamp, and a superseding
    decision must win regardless of storage order.
    """
    rows = (
        (
            await session.execute(
                select(HumanReviewDecision).where(
                    HumanReviewDecision.project_id == project_id,
                    HumanReviewDecision.artifact_id == artifact_id,
                    HumanReviewDecision.review_kind == review_kind,
                )
            )
        )
        .scalars()
        .all()
    )
    return latest_review_decision(rows)


def latest_review_decision(rows: Sequence[HumanReviewDecision]) -> HumanReviewDecision | None:
    """Choose a supersession head, identically for individual gates and batch readers."""
    if not rows:
        return None
    superseded = {row.supersedes_id for row in rows if row.supersedes_id is not None}
    heads = [row for row in rows if row.id not in superseded]
    if not heads:
        # Defensive: a cycle would leave no head; fall back to newest by id.
        return max(rows, key=lambda row: (row.created_at, str(row.id)))
    return max(heads, key=lambda row: (row.created_at, str(row.id)))


AdmissionTarget = tuple[UUID, UUID, str]
ReviewSubject = tuple[UUID, UUID, ReviewKind]


async def _review_runs_for_targets(
    session: AsyncSession, *, project_id: UUID, subjects: set[ReviewSubject]
) -> dict[ReviewSubject, NodeRun]:
    """Exact evidence has priority; legacy fallback is bounded per Shot/kind, not globally."""
    if not subjects:
        return {}
    shot_text = NodeRun.input_snapshot["shot_id"].as_string()
    upstream_text = NodeRun.input_snapshot["upstream_artifact_id"].as_string()
    shot_ids = {str(shot) for shot, _artifact, _kind in subjects}
    artifact_ids = {str(artifact) for _shot, artifact, _kind in subjects}
    node_keys = {REVIEW_NODE_KEYS[kind] for _shot, _artifact, kind in subjects}
    eligible = (
        NodeRun.project_id == project_id,
        GraphNode.node_key.in_(node_keys),
        NodeRun.status.in_(("completed", "cached", "completed_after_cancel", "failed")),
        shot_text.in_(shot_ids),
    )
    newest = (NodeRun.created_at.desc(), NodeRun.attempt_no.desc(), NodeRun.id.desc())
    ranked = (
        select(
            NodeRun.id.label("run_id"),
            shot_text.label("shot_id"),
            upstream_text.label("artifact_id"),
            GraphNode.node_key.label("node_key"),
            func.row_number()
            .over(partition_by=(shot_text, upstream_text, GraphNode.node_key), order_by=newest)
            .label("rank"),
        )
        .join(GraphNode, GraphNode.id == NodeRun.graph_node_id)
        .where(*eligible, upstream_text.in_(artifact_ids))
        .subquery()
    )
    rows = (
        await session.execute(
            select(NodeRun, ranked.c.shot_id, ranked.c.artifact_id, ranked.c.node_key)
            .join(ranked, ranked.c.run_id == NodeRun.id)
            .where(ranked.c.rank == 1)
        )
    ).all()
    exact = {(shot, artifact, key): run for run, shot, artifact, key in rows}
    result = {
        subject: exact[key]
        for subject in subjects
        if (key := (str(subject[0]), str(subject[1]), REVIEW_NODE_KEYS[subject[2]])) in exact
    }
    missing = subjects - result.keys()
    if not missing:
        return result
    fallback_ranked = (
        select(
            NodeRun.id.label("run_id"),
            shot_text.label("shot_id"),
            GraphNode.node_key.label("node_key"),
            func.row_number()
            .over(partition_by=(shot_text, GraphNode.node_key), order_by=newest)
            .label("rank"),
        )
        .join(GraphNode, GraphNode.id == NodeRun.graph_node_id)
        .where(*eligible, shot_text.in_({str(subject[0]) for subject in missing}))
        .subquery()
    )
    fallback_rows = (
        await session.execute(
            select(NodeRun, fallback_ranked.c.shot_id, fallback_ranked.c.node_key)
            .join(fallback_ranked, fallback_ranked.c.run_id == NodeRun.id)
            .where(fallback_ranked.c.rank <= 50)
            .order_by(fallback_ranked.c.rank)
        )
    ).all()
    fallback: dict[tuple[str, str], list[NodeRun]] = {}
    for run, shot, node_key in fallback_rows:
        fallback.setdefault((shot, node_key), []).append(run)
    for subject in missing:
        shot, artifact, kind = subject
        for run in fallback.get((str(shot), REVIEW_NODE_KEYS[kind]), []):
            snapshot = run.input_snapshot or {}
            upstream = snapshot.get("upstream_artifact_id") or snapshot.get("source_artifact_id")
            if upstream is None or str(upstream) == str(artifact):
                result[subject] = run
                break
    return result


async def evaluate_artifact_admissions(
    session: AsyncSession, *, project_id: UUID, targets: Sequence[AdmissionTarget]
) -> dict[AdmissionTarget, StageAdmission]:
    """Batch loading over the same exact admission rule used by individual mutations."""
    if not targets:
        return {}
    kinds: dict[AdmissionTarget, ReviewKind] = {}
    for target in targets:
        kind = STAGE_REVIEW_KIND.get(target[2])
        if kind is None:
            raise ValidationAppError(
                f"unknown production stage: {target[2]}",
                details={"code": "REVIEW_STAGE_UNKNOWN", "supported": sorted(STAGE_REVIEW_KIND)},
            )
        kinds[target] = kind
    artifact_ids = {target[1] for target in targets}
    artifacts = {
        artifact.id: artifact
        for artifact in (
            await session.scalars(
                select(Artifact).where(
                    Artifact.project_id == project_id, Artifact.id.in_(artifact_ids)
                )
            )
        ).all()
    }
    for artifact_id in artifact_ids:
        artifact = artifacts.get(artifact_id)
        if artifact is None:
            raise ValidationAppError(
                "artifact not found in project", details={"code": "ARTIFACT_NOT_FOUND"}
            )
        if artifact.deleted_at is not None:
            raise ValidationAppError("artifact was deleted", details={"code": "ARTIFACT_DELETED"})
    decision_groups: dict[tuple[UUID, str], list[HumanReviewDecision]] = {}
    for stored_decision in (
        await session.scalars(
            select(HumanReviewDecision).where(
                HumanReviewDecision.project_id == project_id,
                HumanReviewDecision.artifact_id.in_(artifact_ids),
                HumanReviewDecision.review_kind.in_(set(kinds.values())),
            )
        )
    ).all():
        decision_groups.setdefault(
            (stored_decision.artifact_id, stored_decision.review_kind), []
        ).append(stored_decision)
    decisions = {subject: latest_review_decision(rows) for subject, rows in decision_groups.items()}
    evidence_ids = {
        decision.review_artifact_id
        for decision in decisions.values()
        if decision is not None and decision.decision == "approved"
    }
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
    runs = await _review_runs_for_targets(
        session,
        project_id=project_id,
        subjects={(target[0], target[1], kind) for target, kind in kinds.items()},
    )
    result: dict[AdmissionTarget, StageAdmission] = {}
    for target, kind in kinds.items():
        shot_id, artifact_id, _stage = target
        decision = decisions.get((artifact_id, kind))
        result[target] = _evaluate_admission(
            artifact=artifacts[artifact_id],
            review_kind=kind,
            decision=decision,
            review_run=runs.get((shot_id, artifact_id, kind)),
            evidence=evidence.get(decision.review_artifact_id) if decision else None,
        )
    return result


async def evaluate_artifact_admission(
    session: AsyncSession, *, project_id: UUID, shot_id: UUID, artifact_id: UUID, stage: str
) -> StageAdmission:
    target = (shot_id, artifact_id, stage)
    return (await evaluate_artifact_admissions(session, project_id=project_id, targets=[target]))[
        target
    ]


def _evaluate_admission(
    *,
    artifact: Artifact,
    review_kind: ReviewKind,
    decision: HumanReviewDecision | None,
    review_run: NodeRun | None,
    evidence: Artifact | None,
) -> StageAdmission:
    """Human verdict, supersession and exact fingerprint rules; no queries or writes."""
    machine_status = None
    review_artifact_id = None
    if review_run is not None:
        machine_status = str((review_run.output_summary or {}).get("status") or "") or None
        review_artifact_id = review_run.result_artifact_id

    requirement = ReviewRequirement(
        review_kind=review_kind,
        node_key=REVIEW_NODE_KEYS[review_kind],
        review_node_run_id=review_run.id if review_run else None,
        review_artifact_id=review_artifact_id,
        machine_status=machine_status,
        decision=decision.decision if decision else None,
        decision_id=decision.id if decision else None,
        decision_reason=decision.reason if decision else None,
        applies=decision is not None,
        blocked_reason=None,
    )

    if decision is not None and decision.decision == "rejected":
        requirement = _with_reason(requirement, "REVIEW_DECISION_REJECTED")
        return StageAdmission(allowed=False, review_kind=review_kind, requirements=[requirement])

    if decision is not None and decision.decision == "approved":
        # Re-derive the subject from today's facts: the media bytes, the review
        # kind and the evidence artifact the decision pointed at. A changed
        # content hash means the person approved something else.
        expected = subject_fingerprint(
            artifact_id=artifact.id,
            artifact_content_hash=artifact.content_hash,
            review_kind=review_kind,
            review_node_run_id=decision.review_node_run_id,
            review_artifact_id=decision.review_artifact_id,
            review_evidence_hash=evidence.content_hash if evidence is not None else None,
        )
        if decision.subject_fingerprint != expected:
            requirement = _with_reason(requirement, "REVIEW_DECISION_STALE")
            requirement = ReviewRequirement(**{**requirement.__dict__, "applies": False})
            return StageAdmission(
                allowed=False, review_kind=review_kind, requirements=[requirement]
            )
        return StageAdmission(allowed=True, review_kind=review_kind, requirements=[requirement])

    # No quality approval yet. A demo-only confirmation remains visible but
    # cannot satisfy this gate; machine evidence still awaits a human verdict.
    reason = (
        "REVIEW_AWAITING_HUMAN"
        if machine_status in _OUTCOME_UNKNOWN_STATUSES
        else "REVIEW_DECISION_MISSING"
    )
    requirement = _with_reason(requirement, reason)
    return StageAdmission(allowed=False, review_kind=review_kind, requirements=[requirement])


def _with_reason(requirement: ReviewRequirement, reason: str | None) -> ReviewRequirement:
    return ReviewRequirement(
        review_kind=requirement.review_kind,
        node_key=requirement.node_key,
        review_node_run_id=requirement.review_node_run_id,
        review_artifact_id=requirement.review_artifact_id,
        machine_status=requirement.machine_status,
        decision=requirement.decision,
        decision_id=requirement.decision_id,
        decision_reason=requirement.decision_reason,
        applies=requirement.applies,
        blocked_reason=reason,
    )


async def record_human_decision(
    session: AsyncSession,
    *,
    project_id: UUID,
    shot_id: UUID,
    artifact_id: UUID,
    review_node_run_id: UUID,
    review_kind: ReviewKind,
    decision: ReviewDecision,
    reason: str,
    actor_id: UUID,
    shot_version: int,
    request_key: str,
) -> HumanReviewDecision:
    """Append one human decision; a retry with the same key returns the original."""
    if review_kind not in REVIEW_NODE_KEYS:
        raise ValidationAppError(
            f"unsupported review kind: {review_kind}",
            details={"code": "REVIEW_KIND_UNSUPPORTED", "supported": sorted(REVIEW_NODE_KEYS)},
        )
    if not reason.strip():
        raise ValidationAppError(
            "a decision needs a reason", details={"code": "REVIEW_REASON_REQUIRED"}
        )
    key = request_key.strip()
    if not key:
        raise ValidationAppError("Idempotency-Key must not be blank")
    request_hash = review_request_hash(
        artifact_id=artifact_id,
        review_node_run_id=review_node_run_id,
        review_kind=review_kind,
        decision=decision,
        reason=reason,
        shot_version=shot_version,
    )
    existing = (
        await session.execute(
            select(HumanReviewDecision).where(
                HumanReviewDecision.project_id == project_id,
                HumanReviewDecision.request_key == key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.request_hash != request_hash:
            raise ConflictError(
                "this decision request key was already used with a different request",
                details={
                    "code": "REVIEW_DECISION_REQUEST_REUSED",
                    "decision_id": str(existing.id),
                },
            )
        return existing

    # Key-only idempotency is not enough for this operation: the reviewer panel
    # mints a fresh key per page load, so pressing the same button again after a
    # reload would append a byte-identical second decision.  The same judgement
    # on the same Artifact is one decision; the stored row is returned instead.
    # A changed verdict or reason still appends (superseding) as before.
    latest = await _latest_decision(
        session, project_id=project_id, artifact_id=artifact_id, review_kind=review_kind
    )
    if latest is not None and judgement_fingerprint(
        artifact_id=artifact_id,
        review_kind=review_kind,
        decision=decision,
        reason=reason.strip(),
    ) == judgement_fingerprint(
        artifact_id=latest.artifact_id,
        review_kind=latest.review_kind,
        decision=latest.decision,
        reason=latest.reason,
    ):
        return latest

    artifact = await session.get(Artifact, artifact_id)
    if artifact is None or artifact.project_id != project_id:
        raise ValidationAppError(
            "artifact not found in project", details={"code": "ARTIFACT_NOT_FOUND"}
        )
    review_run = await session.get(NodeRun, review_node_run_id)
    if review_run is None or review_run.project_id != project_id:
        raise ValidationAppError(
            "review run not found in project", details={"code": "REVIEW_RUN_NOT_FOUND"}
        )
    # New review snapshots carry their exact target. Reject an explicit
    # mismatch, while retaining compatibility with historical evidence rows
    # that predate target fields and can only be bound by the stored decision.
    snapshot = dict(review_run.input_snapshot or {})
    snapshot_shot_id = snapshot.get("shot_id")
    snapshot_artifact_id = snapshot.get("upstream_artifact_id") or snapshot.get(
        "source_artifact_id"
    )
    if (snapshot_shot_id is not None and str(snapshot_shot_id) != str(shot_id)) or (
        snapshot_artifact_id is not None and str(snapshot_artifact_id) != str(artifact_id)
    ):
        raise ValidationAppError(
            "review target does not belong to this shot and Artifact",
            details={"code": "REVIEW_TARGET_MISMATCH"},
        )
    if review_run.result_artifact_id is None:
        raise ValidationAppError(
            "review run has no evidence artifact",
            details={"code": "REVIEW_EVIDENCE_MISSING"},
        )
    review_artifact = await session.get(Artifact, review_run.result_artifact_id)
    if review_artifact is None or review_artifact.project_id != project_id:
        raise ValidationAppError(
            "review evidence artifact is unavailable",
            details={"code": "REVIEW_EVIDENCE_MISSING"},
        )

    previous = await _latest_decision(
        session, project_id=project_id, artifact_id=artifact_id, review_kind=review_kind
    )
    row = HumanReviewDecision(
        project_id=project_id,
        shot_id=shot_id,
        artifact_id=artifact_id,
        review_node_run_id=review_node_run_id,
        review_artifact_id=review_artifact.id,
        review_kind=review_kind,
        subject_fingerprint=subject_fingerprint(
            artifact_id=artifact.id,
            artifact_content_hash=artifact.content_hash,
            review_kind=review_kind,
            review_node_run_id=review_node_run_id,
            review_artifact_id=review_artifact.id,
            review_evidence_hash=review_artifact.content_hash,
        ),
        shot_version_at_decision=shot_version,
        decision=decision,
        reason=reason.strip(),
        actor_id=actor_id,
        request_key=key,
        request_hash=request_hash,
        supersedes_id=previous.id if previous is not None else None,
    )
    session.add(row)
    await session.flush()
    return row


__all__ = [
    "REVIEW_NODE_KEYS",
    "STAGE_REVIEW_KIND",
    "ReviewKind",
    "ReviewRequirement",
    "StageAdmission",
    "evaluate_artifact_admission",
    "evaluate_artifact_admissions",
    "judgement_fingerprint",
    "record_human_decision",
    "review_request_hash",
    "subject_fingerprint",
]
