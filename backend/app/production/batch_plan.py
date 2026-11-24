"""Project-level production batch preview (I8b).

A user decides production for a whole project, not one shot at a time.  This
read model answers "what can start now, what is blocked, and how many paid
operations would a batch create" without writing anything, without calling a
Provider, and without weakening the existing per-command gates: it only reports
the same plans the Workbench would build, plus their blockers.

The fingerprint freezes the ordered set of shots and their plan fingerprints so a
later authorized batch create can prove it acts on exactly this preview.
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project
from app.assets.models import Episode, Scene, Shot
from app.production.workbench_execution import (
    PlanStage,
    WorkbenchExecutionError,
    WorkbenchExecutionInput,
    WorkbenchExecutionService,
)
from app.shared.errors import ValidationAppError

# The preview deliberately covers production media stages only. Editing and
# delivery stay in their own phase; a batch cannot queue them.
BATCH_STAGES: dict[PlanStage, str] = {
    "image_keyframe": "text_to_image",
    "video": "image_to_video",
}


class ProductionBatchItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shot_id: UUID
    episode_id: UUID
    episode_number: int
    scene_id: UUID
    scene_number: int
    shot_number: int
    stage: str
    status: Literal["planned", "blocked", "formal"]
    plan_fingerprint: str | None
    blockers: list[str]


class ProductionBatchPlanRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    stage: str
    items: list[ProductionBatchItem]
    planned_count: int
    blocked_count: int
    formal_count: int
    max_operations: int
    batch_fingerprint: str


def _fingerprint(*, project_id: UUID, stage: str, items: list[ProductionBatchItem]) -> str:
    payload = {
        "project_id": str(project_id),
        "stage": stage,
        "items": [
            {"shot_id": str(item.shot_id), "plan": item.plan_fingerprint}
            for item in items
            if item.status == "planned"
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class ProductionBatchPlanService:
    """Caller establishes authenticated workspace and project ownership first."""

    def __init__(self, session: AsyncSession, *, user_id: UUID) -> None:
        self._session = session
        self._user_id = user_id

    async def preview(
        self,
        *,
        project: Project,
        stage: PlanStage,
        shot_ids: list[UUID] | None = None,
    ) -> ProductionBatchPlanRead:
        if stage not in BATCH_STAGES:
            raise ValidationAppError(
                "this stage cannot be queued as a production batch",
                details={"code": "BATCH_STAGE_UNSUPPORTED", "stage": stage},
            )
        query = (
            select(Shot, Scene, Episode)
            .join(Scene, Scene.id == Shot.scene_id)
            .join(Episode, Episode.id == Scene.episode_id)
            .where(Episode.project_id == project.id)
            .order_by(Episode.episode_number, Scene.scene_number, Shot.sort_order, Shot.shot_number)
        )
        if shot_ids is not None:
            query = query.where(Shot.id.in_(shot_ids))
        rows = (await self._session.execute(query)).all()
        if shot_ids is not None and {shot.id for shot, _scene, _episode in rows} != set(shot_ids):
            # Never silently drop a requested shot out of the frozen set.
            raise ValidationAppError(
                "a requested shot is outside this project",
                details={"code": "BATCH_SHOT_UNKNOWN"},
            )

        service = WorkbenchExecutionService(self._session, user_id=self._user_id)
        stage_value = _formal_pointer(stage)
        items: list[ProductionBatchItem] = []
        for shot, scene, episode in rows:
            if getattr(shot, stage_value) is not None:
                items.append(
                    _item(
                        shot, scene, episode, stage=stage, status="formal", plan=None, blockers=[]
                    )
                )
                continue
            try:
                plan = await service.build_plan(
                    project=project,
                    execution_input=WorkbenchExecutionInput(
                        project_id=project.id,
                        shot_id=shot.id,
                        stage=stage,
                        prompt=_prompt_for(shot, stage),
                        semantic_intent={"intent": "shot_keyframe"},
                        mode_id=BATCH_STAGES[stage],
                        expected_shot_version=shot.version,
                    ),
                )
            except WorkbenchExecutionError as exc:
                code = str(exc.details.get("code") or exc.code)
                items.append(
                    _item(
                        shot,
                        scene,
                        episode,
                        stage=stage,
                        status="blocked",
                        plan=None,
                        blockers=[code],
                    )
                )
                continue
            items.append(
                _item(
                    shot,
                    scene,
                    episode,
                    stage=stage,
                    status="planned",
                    plan=plan.plan_fingerprint,
                    blockers=[],
                )
            )

        planned = sum(1 for item in items if item.status == "planned")
        blocked = sum(1 for item in items if item.status == "blocked")
        formal = sum(1 for item in items if item.status == "formal")
        return ProductionBatchPlanRead(
            project_id=project.id,
            stage=stage,
            items=items,
            planned_count=planned,
            blocked_count=blocked,
            formal_count=formal,
            # One paid operation per planned shot; a caller may only lower it.
            max_operations=planned,
            batch_fingerprint=_fingerprint(project_id=project.id, stage=stage, items=items),
        )


def _formal_pointer(stage: PlanStage) -> str:
    if stage == "image_keyframe":
        return "formal_keyframe_artifact_id"
    return "formal_video_artifact_id"


def _prompt_for(shot: Shot, stage: PlanStage) -> str:
    prompt = (shot.image_prompt if stage == "image_keyframe" else shot.video_prompt) or ""
    return prompt.strip() or (shot.visual_description or "").strip() or "shot"


def _item(
    shot: Shot,
    scene: Scene,
    episode: Episode,
    *,
    stage: PlanStage,
    status: Literal["planned", "blocked", "formal"],
    plan: str | None,
    blockers: list[str],
) -> ProductionBatchItem:
    return ProductionBatchItem(
        shot_id=shot.id,
        episode_id=episode.id,
        episode_number=episode.episode_number,
        scene_id=scene.id,
        scene_number=scene.scene_number,
        shot_number=shot.shot_number,
        stage=stage,
        status=status,
        plan_fingerprint=plan,
        blockers=blockers,
    )


__all__ = [
    "BATCH_STAGES",
    "ProductionBatchItem",
    "ProductionBatchPlanRead",
    "ProductionBatchPlanService",
]
