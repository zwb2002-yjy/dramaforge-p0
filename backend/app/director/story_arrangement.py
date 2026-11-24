"""Persist and resolve formal Story Apply results for the registered episode arrangement step."""

from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Episode
from app.contracts.delivery_verification import (
    AppliedEpisodeReceipt,
    BoundDeliveryOutput,
    DeliveryPlanRef,
    DeliveryTarget,
)
from app.director.business_flow_models import (
    DirectorBusinessFlowStep,
    DirectorBusinessFlowStepAttempt,
)
from app.director.business_flows import content_hash
from app.director.proposal_models import DirectorProposalItem
from app.shared.errors import ConflictError


def _key(item: DirectorProposalItem) -> str:
    return f"story-apply:{item.id}"


def _decision_hash(item: DirectorProposalItem) -> str:
    return content_hash(
        {
            "command": item.command,
            "payload": item.payload,
            "expected_version": item.expected_target_version,
        }
    )


async def check_story_replay(
    db: AsyncSession,
    item: DirectorProposalItem,
    plan: DeliveryPlanRef,
) -> None:
    attempt = await db.scalar(
        select(DirectorBusinessFlowStepAttempt).where(
            DirectorBusinessFlowStepAttempt.project_id == item.project_id,
            DirectorBusinessFlowStepAttempt.command_key == _key(item),
        )
    )
    if (
        attempt is None
        or attempt.supervisor_run_id != plan.master_run_id
        or attempt.plan_id != plan.plan_id
        or attempt.control_epoch != plan.control_epoch
        or attempt.status != "succeeded"
        or (attempt.receipt_ref or {}).get("decision_hash") != _decision_hash(item)
    ):
        raise ConflictError("此采纳回执不属于所选计划")


async def check_story_destination(
    db: AsyncSession,
    project_id: UUID,
    proposal_id: UUID,
    plan: DeliveryPlanRef,
) -> None:
    # A partially accepted proposal keeps its destination across separate decisions.
    other = await db.scalar(
        select(DirectorBusinessFlowStepAttempt.id)
        .where(
            DirectorBusinessFlowStepAttempt.project_id == project_id,
            DirectorBusinessFlowStepAttempt.action_key == "story.upsert_episode",
            DirectorBusinessFlowStepAttempt.receipt_ref["proposal_id"].as_string()
            == str(proposal_id),
            DirectorBusinessFlowStepAttempt.plan_id != plan.plan_id,
        )
        .limit(1)
    )
    if other is not None:
        raise ConflictError("此剧本提案已有其他计划的分集采纳回执")


async def record_episode(
    db: AsyncSession,
    binding: BoundDeliveryOutput,
    item: DirectorProposalItem,
    episode: Episode,
) -> tuple[DirectorBusinessFlowStep, bool]:
    step = await db.get(DirectorBusinessFlowStep, binding.step_id)
    assert step is not None
    count = step.input_refs["planned_episode_count"]
    if (
        type(count) is not int
        or not 1 <= episode.episode_number <= count
        or step.status != "waiting_user"
        or episode.project_id != binding.project_id
    ):
        raise ConflictError(
            "分集超出范围或该计划的分集清单已确定",
            details={"code": "STORY_ARRANGEMENT_CLOSED"},
        )
    ref = AppliedEpisodeReceipt(
        proposal_id=item.proposal_id,
        item_id=item.id,
        episode_id=episode.id,
        episode_number=episode.episode_number,
        episode_version=episode.version,
        decision_hash=_decision_hash(item),
    ).model_dump(mode="json")
    number = await db.scalar(
        select(func.max(DirectorBusinessFlowStepAttempt.attempt_no)).where(
            DirectorBusinessFlowStepAttempt.step_id == step.id,
        )
    )
    db.add(
        DirectorBusinessFlowStepAttempt(
            project_id=binding.project_id,
            step_id=step.id,
            instance_id=binding.flow_instance_id,
            supervisor_run_id=binding.master_run_id,
            plan_id=binding.plan_id,
            plan_revision=binding.plan_revision,
            scope_type="project",
            scope_entity_id=binding.project_id,
            control_epoch=binding.control_epoch,
            attempt_no=(number or 0) + 1,
            input_hash=content_hash(step.input_refs),
            payload_hash=content_hash(ref),
            input_snapshot=binding.model_dump(mode="json"),
            action_kind="apply",
            action_key="story.upsert_episode",
            command_key=_key(item),
            status="succeeded",
            revision=1,
            receipt_ref=ref,
            result_refs=[ref],
        )
    )
    current = {r["episode_number"]: r for r in step.result_refs if isinstance(r, dict)}
    current[episode.episode_number] = ref
    step.result_refs = [current[key] for key in sorted(current)]
    step.revision += 1
    if len(current) == count:
        # Earlier partial decisions may have been superseded while the last
        # episode was being authored. Keep those numbers open for another Apply.
        expected = {
            UUID(str(r["episode_id"])): (n, r["episode_version"]) for n, r in current.items()
        }
        rows = await db.execute(
            select(Episode.id, Episode.episode_number, Episode.version)
            .where(
                Episode.project_id == binding.project_id,
                Episode.id.in_(expected),
            )
            .order_by(Episode.id)
            .with_for_update(read=True)
        )
        if {episode_id: (n, version) for episode_id, n, version in rows} == expected:
            step.status = "succeeded"
            step.wait_reason = None
    await db.flush()
    return step, step.status == "succeeded"


async def arrangement_targets(
    db: AsyncSession,
    binding: BoundDeliveryOutput,
    count: int,
) -> tuple[list[DeliveryTarget], list[tuple[int, int]], list[str], list[dict[str, object]]]:
    rows = await db.scalars(
        select(DirectorBusinessFlowStepAttempt)
        .where(
            DirectorBusinessFlowStepAttempt.step_id == binding.step_id,
            DirectorBusinessFlowStepAttempt.instance_id == binding.flow_instance_id,
            DirectorBusinessFlowStepAttempt.project_id == binding.project_id,
            DirectorBusinessFlowStepAttempt.supervisor_run_id == binding.master_run_id,
            DirectorBusinessFlowStepAttempt.plan_id == binding.plan_id,
            DirectorBusinessFlowStepAttempt.plan_revision == binding.plan_revision,
            DirectorBusinessFlowStepAttempt.action_key == "story.upsert_episode",
            DirectorBusinessFlowStepAttempt.status == "succeeded",
        )
        .order_by(DirectorBusinessFlowStepAttempt.attempt_no)
        .with_for_update(read=True)
    )
    refs: dict[int, AppliedEpisodeReceipt] = {}
    reasons: list[str] = []
    for attempt in rows:
        data = attempt.receipt_ref or {}
        try:
            ref = AppliedEpisodeReceipt.model_validate(data)
        except ValidationError:
            reasons.append("STORY_RECEIPT_INVALID")
            continue
        if (
            ref.episode_number > count
            or attempt.action_kind != "apply"
            or attempt.input_hash != content_hash({"planned_episode_count": count})
            or attempt.control_epoch > binding.control_epoch
            or attempt.command_key != f"story-apply:{ref.item_id}"
            or attempt.payload_hash != content_hash(data)
            or attempt.input_snapshot
            != binding.model_copy(update={"control_epoch": attempt.control_epoch}).model_dump(
                mode="json"
            )
        ):
            reasons.append("STORY_RECEIPT_INVALID")
            continue
        refs[ref.episode_number] = ref
    items = {
        i.id: i
        for i in await db.scalars(
            select(DirectorProposalItem)
            .where(
                DirectorProposalItem.project_id == binding.project_id,
                DirectorProposalItem.id.in_([r.item_id for r in refs.values()]),
            )
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
    }
    episodes = {
        e.id: e
        for e in await db.scalars(
            select(Episode)
            .where(
                Episode.project_id == binding.project_id,
                Episode.id.in_([r.episode_id for r in refs.values()]),
            )
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
    }
    evidence: list[dict[str, object]] = []
    targets = []
    missing = []
    next_number = 1
    for number, ref in sorted(refs.items()):
        item, episode = items.get(ref.item_id), episodes.get(ref.episode_id)
        if (
            not item
            or item.proposal_id != ref.proposal_id
            or item.command != "story.upsert_episode"
            or item.status != "accepted"
            or _decision_hash(item) != ref.decision_hash
        ):
            reasons.append("STORY_RECEIPT_INVALID")
            continue
        if (
            not episode
            or episode.version != ref.episode_version
            or episode.episode_number != number
        ):
            reasons.append("STORY_EPISODE_CHANGED")
            continue
        if number > next_number:
            missing.append((next_number, number - 1))
        next_number = number + 1
        evidence.append(ref.model_dump(mode="json"))
        targets.append(DeliveryTarget(episode_id=ref.episode_id, episode_number=number))
    if next_number <= count:
        missing.append((next_number, count))
    return targets, missing, sorted(set(reasons)), evidence
