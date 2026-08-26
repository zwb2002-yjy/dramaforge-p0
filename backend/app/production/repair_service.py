"""P6-04/05/06 Manual repair service (03 §56-58).

Builds a repair plan from open review annotations and executes a V1 repair
(``rerun_video`` or ``regenerate_keyframe_then_video``) by dispatching queued
NodeRuns through the WorkbenchExecutionService. No local inpaint / splice.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project, User
from app.assets.models import Shot
from app.delivery.models import ReviewAnnotation
from app.execution.models import NodeRun
from app.production.workbench_execution import (
    WorkbenchExecutionInput,
    WorkbenchExecutionService,
)
from app.shared.errors import ValidationAppError

RepairOption = Literal["rerun_video", "regenerate_keyframe_then_video"]


class RepairPlanRead(BaseModel):
    """Repair plan computed from open annotations (03 §57)."""

    model_config = ConfigDict(extra="forbid")

    shot_id: UUID
    repair_options: list[RepairOption]
    suggested_option: RepairOption
    affected_nodes: list[str]
    retained_assets: list[str]
    expected_rerun_scope: str
    annotation_count: int


class RepairService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def build_repair_plan(
        self,
        *,
        project: Project,
        shot_id: UUID,
    ) -> RepairPlanRead:
        """Derive a repair plan from open annotations on the shot."""
        shot = await self._session.get(Shot, shot_id)
        if shot is None or shot.project_id != project.id:
            raise ValidationAppError("shot not found", details={"code": "SHOT_NOT_FOUND"})
        annotations = (
            await self._session.execute(
                select(ReviewAnnotation).where(
                    ReviewAnnotation.project_id == project.id,
                    ReviewAnnotation.shot_id == shot_id,
                    ReviewAnnotation.status == "open",
                )
            )
        ).scalars().all()

        has_video_range = any(
            annotation.time_start is not None or annotation.time_end is not None
            for annotation in annotations
        )
        has_region = any(
            annotation.x is not None
            or annotation.width is not None
            for annotation in annotations
        )
        has_keyframe = shot.formal_keyframe_artifact_id is not None

        if has_video_range:
            suggested: RepairOption = "regenerate_keyframe_then_video"
            affected = ["keyframe", "video"]
            retained: list[str] = []
            scope = "keyframe_then_video"
        elif has_region and has_keyframe:
            suggested = "rerun_video"
            affected = ["video"]
            retained = ["formal_keyframe"]
            scope = "video"
        else:
            suggested = "rerun_video"
            affected = ["video"]
            retained = []
            scope = "video"

        return RepairPlanRead(
            shot_id=shot_id,
            repair_options=["rerun_video", "regenerate_keyframe_then_video"],
            suggested_option=suggested,
            affected_nodes=affected,
            retained_assets=retained,
            expected_rerun_scope=scope,
            annotation_count=len(annotations),
        )

    async def execute_repair(
        self,
        *,
        project: Project,
        user: User,
        shot_id: UUID,
        repair_option: RepairOption,
        idempotency_key: str,
    ) -> NodeRun:
        """Dispatch the repair rerun (V1). Returns the created queued NodeRun."""
        shot = await self._session.get(Shot, shot_id)
        if shot is None or shot.project_id != project.id:
            raise ValidationAppError("shot not found", details={"code": "SHOT_NOT_FOUND"})
        service = WorkbenchExecutionService(self._session, user_id=user.id)
        if repair_option == "rerun_video":
            if shot.formal_keyframe_artifact_id is None:
                raise ValidationAppError(
                    "rerun_video requires a formal keyframe",
                    details={"code": "NO_FORMAL_KEYFRAME"},
                )
            return await service.create_and_dispatch(
                project=project,
                execution_input=WorkbenchExecutionInput(
                    project_id=project.id,
                    shot_id=shot_id,
                    stage="video",
                    prompt=shot.video_prompt or "rerun video",
                    semantic_intent={"intent": "shot_video", "repair": repair_option},
                    mode_id="explicit_binding",
                ),
                idempotency_key_override=f"repair:{idempotency_key}",
            )
        # regenerate_keyframe_then_video: dispatch a keyframe candidate first.
        return await service.create_and_dispatch(
            project=project,
            execution_input=WorkbenchExecutionInput(
                project_id=project.id,
                shot_id=shot_id,
                stage="image_keyframe",
                prompt=shot.image_prompt or "regenerate keyframe",
                semantic_intent={"intent": "shot_keyframe", "repair": repair_option},
                mode_id="explicit_binding",
            ),
            idempotency_key_override=f"repair:{idempotency_key}",
        )
