"""P3-04/P3-06 scene workspace and shot workbench snapshots (backend aggregation)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import User
from app.access.projects import ProjectService
from app.assets.models import Asset, AssetVersion, Episode, Scene, Shot
from app.assets.scene_service import _artifact_summary
from app.execution.models import Artifact, NodeRun
from app.production.formal_selection import list_formal_candidates
from app.production.models import ExperimentBranch, ShotReferenceBinding
from app.shared.errors import NotFoundError


def _shot_dict(shot: Shot) -> dict[str, object]:
    return {
        "id": shot.id,
        "project_id": shot.project_id,
        "scene_id": shot.scene_id,
        "shot_number": shot.shot_number,
        "shot_type": shot.shot_type,
        "camera_move": shot.camera_move,
        "visual_description": shot.visual_description,
        "dialogue": shot.dialogue,
        "duration_seconds": str(shot.duration_seconds),
        "status": shot.status,
        "sort_order": shot.sort_order,
        "version": shot.version,
        "director_state": dict(shot.director_state or {}),
        "image_prompt": shot.image_prompt,
        "video_prompt": shot.video_prompt,
        "formal_keyframe_artifact_id": shot.formal_keyframe_artifact_id,
        "formal_video_artifact_id": shot.formal_video_artifact_id,
        "formal_composite_artifact_id": shot.formal_composite_artifact_id,
    }


class SceneWorkspaceService:
    """Scene-scoped snapshot: scene + its shots + bindings + trace summary."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_workspace(
        self, *, project_id: UUID, scene_id: UUID, actor: User
    ) -> dict[str, object]:
        await ProjectService(self._session).get_project_for_owner(
            project_id=project_id, actor=actor
        )
        scene_row = (
            await self._session.execute(
                select(Scene, Episode.episode_number)
                .join(Episode, Episode.id == Scene.episode_id)
                .where(Scene.id == scene_id, Episode.project_id == project_id)
            )
        ).one_or_none()
        if scene_row is None:
            raise NotFoundError("scene not found")
        scene, episode_number = scene_row
        shots = (
            await self._session.execute(
                select(Shot)
                .where(Shot.scene_id == scene.id, Shot.project_id == project_id)
                .order_by(Shot.shot_number, Shot.sort_order)
            )
        ).scalars().all()
        shot_ids = [shot.id for shot in shots]
        shot_dicts = {shot.id: _shot_dict(shot) for shot in shots}

        bindings: dict[UUID, list[ShotReferenceBinding]] = {}
        if shot_ids:
            binding_rows = (
                await self._session.execute(
                    select(ShotReferenceBinding)
                    .where(
                        ShotReferenceBinding.project_id == project_id,
                        ShotReferenceBinding.shot_id.in_(shot_ids),
                    )
                    .order_by(ShotReferenceBinding.sort_order)
                )
            ).scalars().all()
            for binding in binding_rows:
                bindings.setdefault(binding.shot_id, []).append(binding)

        # Concrete formal candidates come from the existing NodeRun ->
        # Artifact lineage.  Experiment branches remain in this opaque
        # collection for backwards-compatible workspace consumers, but never
        # substitute for an Artifact candidate in the formal action.
        candidates: dict[UUID, list[dict[str, object]]] = await list_formal_candidates(
            self._session,
            project_id=project_id,
            shot_ids=shot_ids,
        )
        if shot_ids:
            exp_rows = (
                await self._session.execute(
                    select(ExperimentBranch)
                    .where(
                        ExperimentBranch.project_id == project_id,
                        ExperimentBranch.source_shot_id.in_(shot_ids),
                    )
                    .order_by(ExperimentBranch.created_at.desc())
                )
            ).scalars().all()
            for branch in exp_rows:
                if branch.source_shot_id is not None:
                    candidates.setdefault(branch.source_shot_id, []).append(
                        {
                            "id": branch.id,
                            "name": branch.name,
                            "branch_type": branch.branch_type,
                            "status": branch.status,
                            "selected_model": branch.selected_model,
                        }
                    )

        trace = await self._load_trace(project_id=project_id, shot_ids=shot_ids)

        return {
            "scene": {
                "id": scene.id,
                "episode_id": scene.episode_id,
                "episode_number": episode_number,
                "scene_number": scene.scene_number,
                "location_name": scene.location_name,
                "time_of_day": scene.time_of_day,
                "synopsis": scene.synopsis,
                "version": scene.version,
                "design_state": dict(scene.design_state or {}),
            },
            "shots": [shot_dicts[shot_id] for shot_id in shot_ids],
            "references": {
                str(shot_id): [
                    {
                        "id": binding.id,
                        "purpose": binding.purpose,
                        "label": binding.label,
                        "asset_id": binding.asset_id,
                        "asset_version_id": binding.asset_version_id,
                        "artifact_id": binding.artifact_id,
                        "resolution_mode": binding.resolution_mode,
                        "stage": binding.stage,
                        "version": binding.version,
                    }
                    for binding in bindings.get(shot_id, [])
                ]
                for shot_id in shot_ids
            },
            "candidates": {
                str(shot_id): candidates.get(shot_id, []) for shot_id in shot_ids
            },
            "trace": trace,
        }

    async def _load_trace(
        self, *, project_id: UUID, shot_ids: list[UUID]
    ) -> dict[str, list[dict[str, object]]]:
        trace: dict[str, list[dict[str, object]]] = {}
        if not shot_ids:
            return trace
        rows = (
            await self._session.execute(
                select(NodeRun)
                .where(NodeRun.project_id == project_id)
                .order_by(NodeRun.created_at.desc())
                .limit(2000)
            )
        ).scalars().all()
        for run in rows:
            # Extract in Python from the JSON snapshot for portability.
            raw = dict(run.input_snapshot or {})
            shot_id = raw.get("shot_id")
            if shot_id is None:
                continue
            try:
                shot_uuid = UUID(str(shot_id))
            except (TypeError, ValueError):
                continue
            if shot_uuid not in shot_ids:
                continue
            trace.setdefault(str(shot_uuid), []).append(
                {
                    "node_run_id": run.id,
                    "node_key": raw.get("node_key"),
                    "status": run.status,
                    "error_code": run.error_code,
                    "finished_at": run.finished_at,
                    "result_artifact_id": run.result_artifact_id,
                }
            )
        for shot_id in shot_ids:
            trace.setdefault(str(shot_id), [])
            trace[str(shot_id)] = trace[str(shot_id)][:20]
        return trace


class ShotWorkbenchService:
    """P3-06 shot workbench aggregation."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_workbench(
        self, *, project_id: UUID, shot_id: UUID, actor: User
    ) -> dict[str, object]:
        await ProjectService(self._session).get_project_for_owner(
            project_id=project_id, actor=actor
        )
        shot = (
            await self._session.execute(
                select(Shot).where(Shot.id == shot_id, Shot.project_id == project_id)
            )
        ).scalar_one_or_none()
        if shot is None:
            raise NotFoundError("shot not found")
        scene = (
            await self._session.execute(
                select(Scene).where(Scene.id == shot.scene_id)
            )
        ).scalar_one_or_none()
        bindings = (
            await self._session.execute(
                select(ShotReferenceBinding)
                .where(
                    ShotReferenceBinding.project_id == project_id,
                    ShotReferenceBinding.shot_id == shot.id,
                )
                .order_by(ShotReferenceBinding.sort_order)
            )
        ).scalars().all()
        candidates = (
            await self._session.execute(
                select(ExperimentBranch)
                .where(
                    ExperimentBranch.project_id == project_id,
                    ExperimentBranch.source_shot_id == shot.id,
                )
                .order_by(ExperimentBranch.created_at.desc())
            )
        ).scalars().all()
        formal_artifact_ids = [
            artifact_id
            for artifact_id in (
                shot.formal_keyframe_artifact_id,
                shot.formal_video_artifact_id,
                shot.formal_composite_artifact_id,
            )
            if artifact_id is not None
        ]
        artifacts: dict[UUID, Artifact] = {}
        if formal_artifact_ids:
            rows = (
                await self._session.execute(
                    select(Artifact).where(Artifact.id.in_(formal_artifact_ids))
                )
            ).scalars().all()
            artifacts = {artifact.id: artifact for artifact in rows}

        trace_rows = (
            await self._session.execute(
                select(NodeRun)
                .where(NodeRun.project_id == project_id)
                .order_by(NodeRun.created_at.desc())
                .limit(2000)
            )
        ).scalars().all()
        trace: list[dict[str, object]] = []
        for run in trace_rows:
            raw = dict(run.input_snapshot or {})
            if raw.get("shot_id") != str(shot.id) and raw.get("shot_id") != shot.id:
                continue
            trace.append(
                {
                    "node_run_id": run.id,
                    "node_key": raw.get("node_key"),
                    "status": run.status,
                    "error_code": run.error_code,
                    "error_summary": run.error_summary,
                    "finished_at": run.finished_at,
                    "result_artifact_id": run.result_artifact_id,
                }
            )
            if len(trace) >= 20:
                break

        old_version_warnings: list[dict[str, object]] = []
        for binding in bindings:
            if binding.resolution_mode != "pinned_version" or binding.asset_id is None:
                continue
            if binding.asset_version_id is None:
                continue
            asset = (
                await self._session.execute(
                    select(Asset).where(
                        Asset.id == binding.asset_id, Asset.project_id == project_id
                    )
                )
            ).scalar_one_or_none()
            pinned = (
                await self._session.execute(
                    select(AssetVersion).where(
                        AssetVersion.id == binding.asset_version_id,
                        AssetVersion.project_id == project_id,
                    )
                )
            ).scalar_one_or_none()
            if asset is not None and pinned is not None and asset.current_version_id != pinned.id:
                old_version_warnings.append(
                    {
                        "binding_id": binding.id,
                        "asset_id": asset.id,
                        "asset_name": asset.name,
                        "pinned_version_number": pinned.version_number,
                        "current_version_number": asset.version,
                    }
                )

        return {
            "shot": _shot_dict(shot),
            "scene": (
                {
                    "id": scene.id,
                    "scene_number": scene.scene_number,
                    "location_name": scene.location_name,
                    "time_of_day": scene.time_of_day,
                }
                if scene is not None
                else None
            ),
            "prompt": {
                "visual_description": shot.visual_description,
                "image_prompt": shot.image_prompt,
                "video_prompt": shot.video_prompt,
                "director_state": dict(shot.director_state or {}),
            },
            "references": [
                {
                    "id": binding.id,
                    "purpose": binding.purpose,
                    "label": binding.label,
                    "asset_id": binding.asset_id,
                    "asset_version_id": binding.asset_version_id,
                    "artifact_id": binding.artifact_id,
                    "resolution_mode": binding.resolution_mode,
                    "stage": binding.stage,
                    "version": binding.version,
                }
                for binding in bindings
            ],
            "formal_artifacts": {
                "keyframe": (
                    _artifact_summary(artifacts.get(shot.formal_keyframe_artifact_id))
                    if shot.formal_keyframe_artifact_id
                    else None
                ),
                "video": (
                    _artifact_summary(artifacts.get(shot.formal_video_artifact_id))
                    if shot.formal_video_artifact_id
                    else None
                ),
                "composite": (
                    _artifact_summary(artifacts.get(shot.formal_composite_artifact_id))
                    if shot.formal_composite_artifact_id
                    else None
                ),
            },
            "candidates": [
                {
                    "id": branch.id,
                    "name": branch.name,
                    "branch_type": branch.branch_type,
                    "status": branch.status,
                    "selected_model": branch.selected_model,
                }
                for branch in candidates
            ],
            "trace": trace,
            "old_version_warnings": old_version_warnings,
        }
