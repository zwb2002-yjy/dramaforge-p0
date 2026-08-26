"""P7-05 Typed proposal commands (03 §65).

A whitelist of typed commands the Director Assistant may propose. Raw SQL,
arbitrary JSON Patch and direct table writes are forbidden: every command is a
bounded, reviewed operation that re-checks ``expected_target_version`` before
mutating.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import User
from app.assets.models import Scene, Shot
from app.assets.version_service import AssetVersionService
from app.production.experiment_service import (
    ExperimentCreateInput,
    ExperimentService,
)
from app.production.models import ShotReferenceBinding
from app.shared.errors import ValidationAppError

COMMAND_WHITELIST = frozenset(
    {
        "shot.update_director_state",
        "shot.update_image_prompt",
        "shot.update_video_prompt",
        "shot.set_model_override",
        "shot_reference.add",
        "shot_reference.remove",
        "asset_version.promote",
        "scene.update_design",
        "experiment.create",
    }
)

# Commands that mutate a shot and therefore carry expected_target_version.
_SHOT_VERSIONED = frozenset(
    {
        "shot.update_director_state",
        "shot.update_image_prompt",
        "shot.update_video_prompt",
    }
)


class ProposalCommandError(ValidationAppError):
    """Raised when a proposal command is unknown, stale or cannot apply."""


async def _require_shot(
    session: AsyncSession,
    *,
    project_id: UUID,
    payload: dict[str, Any],
    expected_target_version: int | None,
) -> Shot:
    shot_id = payload.get("shot_id")
    if shot_id is None:
        raise ProposalCommandError("payload requires shot_id")
    shot = await session.get(Shot, UUID(str(shot_id)))
    if shot is None or shot.project_id != project_id:
        raise ProposalCommandError("shot not found")
    if expected_target_version is not None and shot.version != expected_target_version:
        raise ProposalCommandError(
            "shot version mismatch: proposal is stale",
            details={"code": "PROPOSAL_STALE"},
        )
    return shot


async def _apply_shot_update(
    session: AsyncSession,
    *,
    project_id: UUID,
    command: str,
    payload: dict[str, Any],
    expected_target_version: int | None,
) -> None:
    shot = await _require_shot(
        session, project_id=project_id, payload=payload,
        expected_target_version=expected_target_version,
    )
    if command == "shot.update_director_state":
        shot.director_state = dict(payload.get("director_state") or {})
    elif command == "shot.update_image_prompt":
        shot.image_prompt = str(payload.get("image_prompt", ""))
    elif command == "shot.update_video_prompt":
        shot.video_prompt = str(payload.get("video_prompt", ""))
    shot.version = (shot.version or 1) + 1
    await session.flush()


async def _apply_reference(
    session: AsyncSession,
    *,
    project_id: UUID,
    command: str,
    payload: dict[str, Any],
    actor_id: UUID,
) -> None:
    shot_id = payload.get("shot_id")
    if shot_id is None:
        raise ProposalCommandError("payload requires shot_id")
    shot = await session.get(Shot, UUID(str(shot_id)))
    if shot is None or shot.project_id != project_id:
        raise ProposalCommandError("shot not found")
    purpose = str(payload.get("purpose", "generic_reference"))
    if command == "shot_reference.add":
        asset_id = payload.get("asset_id")
        if asset_id is None:
            raise ProposalCommandError("payload requires asset_id")
        binding = ShotReferenceBinding(
            project_id=project_id,
            shot_id=shot.id,
            purpose=purpose,
            asset_id=UUID(str(asset_id)),
            resolution_mode=str(payload.get("resolution_mode", "current_formal")),
            sort_order=int(payload.get("sort_order", 0)),
            created_by=actor_id,
        )
        session.add(binding)
    elif command == "shot_reference.remove":
        binding_id = payload.get("binding_id")
        if binding_id is None:
            raise ProposalCommandError("payload requires binding_id")
        existing_binding = await session.get(ShotReferenceBinding, UUID(str(binding_id)))
        if existing_binding is None or existing_binding.project_id != project_id:
            raise ProposalCommandError("binding not found")
        await session.delete(existing_binding)
    await session.flush()


async def _apply_scene_update(
    session: AsyncSession,
    *,
    project_id: UUID,
    payload: dict[str, Any],
    expected_target_version: int | None,
) -> None:
    scene_id = payload.get("scene_id")
    if scene_id is None:
        raise ProposalCommandError("payload requires scene_id")
    scene = await session.get(Scene, UUID(str(scene_id)))
    if scene is None:
        raise ProposalCommandError("scene not found")
    scene.design_state = dict(payload.get("design_state") or {})
    scene.version = (scene.version or 1) + 1
    await session.flush()


async def _apply_asset_promote(
    session: AsyncSession,
    *,
    project_id: UUID,
    payload: dict[str, Any],
    actor_id: UUID,
) -> None:
    version_id = payload.get("asset_version_id")
    asset_id = payload.get("asset_id")
    if version_id is None or asset_id is None:
        raise ProposalCommandError("payload requires asset_version_id and asset_id")
    actor = await session.get(User, actor_id)
    if actor is None:
        raise ProposalCommandError("actor not found")
    await AssetVersionService(session).promote(
        project_id=project_id,
        asset_id=UUID(str(asset_id)),
        version_id=UUID(str(version_id)),
        actor=actor,
    )


async def _apply_experiment_create(
    session: AsyncSession,
    *,
    project_id: UUID,
    payload: dict[str, Any],
    actor_id: UUID,
) -> None:
    from app.access.models import Project

    project = await session.get(Project, project_id)
    if project is None:
        raise ProposalCommandError("project not found")
    actor = await session.get(User, actor_id)
    if actor is None:
        raise ProposalCommandError("actor not found")
    await ExperimentService(session).create_experiment(
        project=project,
        actor=actor,
        experiment_input=ExperimentCreateInput(
            name=str(payload.get("name", "assistant experiment")),
            shot_ids=[UUID(str(shot_id)) for shot_id in (payload.get("shot_ids") or [])],
            model_overrides=dict(payload.get("model_overrides") or {}),
            idempotency_key=str(payload.get("idempotency_key") or f"assistant-{UUID(int=0)}"),
        ),
    )
    await session.flush()


class ProposalCommandRegistry:
    """Typed command registry (03 §65). Only whitelisted commands apply."""

    def __init__(self, session: AsyncSession, *, actor_id: UUID) -> None:
        self._session = session
        self._actor_id = actor_id

    def is_known(self, command: str) -> bool:
        return command in COMMAND_WHITELIST

    async def apply(
        self,
        *,
        project_id: UUID,
        command: str,
        payload: dict[str, Any],
        expected_target_version: int | None = None,
    ) -> None:
        if not self.is_known(command):
            raise ProposalCommandError(
                f"unknown proposal command: {command}",
                details={"code": "UNKNOWN_COMMAND"},
            )
        if command in _SHOT_VERSIONED:
            await _apply_shot_update(
                self._session, project_id=project_id, command=command,
                payload=payload, expected_target_version=expected_target_version,
            )
        elif command in ("shot_reference.add", "shot_reference.remove"):
            await _apply_reference(
                self._session, project_id=project_id, command=command,
                payload=payload, actor_id=self._actor_id,
            )
        elif command == "scene.update_design":
            await _apply_scene_update(
                self._session, project_id=project_id, payload=payload,
                expected_target_version=expected_target_version,
            )
        elif command == "asset_version.promote":
            await _apply_asset_promote(
                self._session, project_id=project_id, payload=payload,
                actor_id=self._actor_id,
            )
        elif command == "shot.set_model_override":
            # A model override is a model-swap experiment (P5 semantics).
            await _apply_experiment_create(
                self._session, project_id=project_id,
                payload={
                    **payload,
                    "model_overrides": payload.get("model_overrides") or {},
                    "name": "assistant model override",
                    "idempotency_key": str(payload.get("idempotency_key")
                                           or f"assistant-override-{UUID(int=0)}"),
                },
                actor_id=self._actor_id,
            )
        elif command == "experiment.create":
            await _apply_experiment_create(
                self._session, project_id=project_id, payload=payload, actor_id=self._actor_id
            )
        else:  # pragma: no cover - registry covers all whitelisted commands
            raise ProposalCommandError(f"command not implemented: {command}")
