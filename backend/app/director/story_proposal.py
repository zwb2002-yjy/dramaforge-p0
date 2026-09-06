"""Story authoring proposal service (V1 G1).

A proposal is a typed diff over the current canonical Story graph.  It is
created from a Markdown script draft and persisted as DirectorProposal /
DirectorProposalItem rows.  Proposal creation and preview never mutate
ScriptDocument / Episode / Scene / Shot rows; application is delegated to the
shared ProposalCommandRegistry so only explicitly accepted operations apply.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import User
from app.assets.models import Episode, Scene, ScriptDocument, Shot
from app.assets.script_import import ParsedScript, parse_script_markdown
from app.director.assistant_models import DirectorMessage, DirectorThread
from app.director.proposal_models import DirectorProposal, DirectorProposalItem
from app.shared.errors import ValidationAppError


@dataclass(frozen=True)
class ProposalItemInput:
    command: str
    payload: dict[str, object]
    expected_target_version: int | None
    rationale: str
    action: str
    key: str


@dataclass(frozen=True)
class StoryProposalResult:
    proposal: DirectorProposal
    items: list[DirectorProposalItem]
    operations: list[dict[str, object]]


async def _get_or_create_project_thread(
    session: AsyncSession,
    *,
    project_id: UUID,
    actor: User,
) -> DirectorThread:
    thread = await session.scalar(
        select(DirectorThread).where(
            DirectorThread.project_id == project_id,
            DirectorThread.scope_type == "project",
            DirectorThread.scope_entity_id == project_id,
        )
    )
    if thread is not None:
        return thread
    thread = DirectorThread(
        project_id=project_id,
        scope_type="project",
        scope_entity_id=project_id,
        title="Story authoring",
        created_by=actor.id,
    )
    session.add(thread)
    await session.flush()
    return thread


@dataclass(frozen=True)
class _StorySnapshot:
    episodes: list[Episode]
    scenes: list[Scene]
    shots: list[Shot]

    def episode_by_number(self, number: int) -> Episode | None:
        return next(
            (
                episode
                for episode in self.episodes
                if episode.episode_number == number
            ),
            None,
        )

    def scene_by_episode_number(
        self, episode: Episode, number: int
    ) -> Scene | None:
        return next(
            (
                scene
                for scene in self.scenes
                if scene.episode_id == episode.id
                and scene.scene_number == number
            ),
            None,
        )

    def shot_by_scene(self, scene: Scene, number: int) -> Shot | None:
        return next(
            (
                shot
                for shot in self.shots
                if shot.scene_id == scene.id and shot.shot_number == number
            ),
            None,
        )


async def _load_snapshot(session: AsyncSession, *, project_id: UUID) -> _StorySnapshot:
    episodes = list(
        (
            await session.execute(
                select(Episode)
                .where(Episode.project_id == project_id)
                .order_by(Episode.episode_number, Episode.id)
            )
        )
        .scalars()
        .all()
    )
    scenes: list[Scene] = []
    if episodes:
        scenes = list(
            (
                await session.execute(
                    select(Scene)
                    .where(Scene.episode_id.in_([episode.id for episode in episodes]))
                    .order_by(Scene.scene_number, Scene.id)
                )
            )
            .scalars()
            .all()
        )
    shots: list[Shot] = []
    if scenes:
        shots = list(
            (
                await session.execute(
                    select(Shot)
                    .where(
                        Shot.project_id == project_id,
                        Shot.scene_id.in_([scene.id for scene in scenes]),
                    )
                    .order_by(Shot.sort_order, Shot.shot_number, Shot.id)
                )
            )
            .scalars()
            .all()
        )
    return _StorySnapshot(episodes=episodes, scenes=scenes, shots=shots)


async def _latest_document(session: AsyncSession, *, project_id: UUID) -> ScriptDocument | None:
    return cast(
        "ScriptDocument | None",
        await session.scalar(
            select(ScriptDocument)
            .where(ScriptDocument.project_id == project_id)
            .order_by(ScriptDocument.created_at.desc(), ScriptDocument.id.desc())
            .limit(1)
        ),
    )


def _shot_payload(
    *,
    episode_number: int,
    scene_number: int,
    shot_number: int,
    shot_type: str,
    camera_move: str,
    visual_description: str,
    dialogue: str,
    duration_seconds: Decimal,
    sort_order: int,
    idempotency_key: str,
    action: str,
) -> dict[str, object]:
    return {
        "episode_number": episode_number,
        "scene_number": scene_number,
        "shot_number": shot_number,
        "shot_type": shot_type,
        "camera_move": camera_move,
        "visual_description": visual_description,
        "dialogue": dialogue,
        "duration_seconds": str(duration_seconds),
        "sort_order": sort_order,
        "action": action,
        "idempotency_key": idempotency_key,
    }


def _build_operations(
    *,
    snapshot: _StorySnapshot,
    parsed: ParsedScript,
    document: ScriptDocument | None,
    content_hash: str,
    filename: str,
    raw_text: str,
    brief: str,
    idempotency_key: str,
) -> list[ProposalItemInput]:
    parsed_episode_numbers = {parsed.episode_number}
    parsed_scene_numbers = {scene.scene_number for scene in parsed.scenes}
    operations: list[ProposalItemInput] = []

    # Deletes first so a full acceptance can safely replace the story.
    for episode in snapshot.episodes:
        if episode.episode_number not in parsed_episode_numbers:
            for scene in snapshot.scenes:
                if scene.episode_id != episode.id:
                    continue
                for shot in snapshot.shots:
                    if shot.scene_id == scene.id:
                        operations.append(
                            ProposalItemInput(
                                command="story.delete_shot",
                                payload={
                                    "episode_number": episode.episode_number,
                                    "scene_number": scene.scene_number,
                                    "shot_number": shot.shot_number,
                                    "action": "delete",
                                    "idempotency_key": idempotency_key,
                                },
                                expected_target_version=shot.version,
                                rationale="脚本草稿不再包含该 Episode 下的 Shot",
                                action="delete",
                                key=(
                                    f"shot:{episode.episode_number}."
                                    f"{scene.scene_number}.{shot.shot_number}"
                                ),
                            )
                        )
                operations.append(
                    ProposalItemInput(
                        command="story.delete_scene",
                        payload={
                            "episode_number": episode.episode_number,
                            "scene_number": scene.scene_number,
                            "action": "delete",
                            "idempotency_key": idempotency_key,
                        },
                        expected_target_version=scene.version,
                        rationale="脚本草稿不再包含该 Episode 下的 Scene",
                        action="delete",
                        key=f"scene:{episode.episode_number}.{scene.scene_number}",
                    )
                )
            operations.append(
                ProposalItemInput(
                    command="story.delete_episode",
                    payload={
                        "episode_number": episode.episode_number,
                        "action": "delete",
                        "idempotency_key": idempotency_key,
                    },
                    expected_target_version=episode.version,
                    rationale="脚本草稿不再包含该 Episode",
                    action="delete",
                    key=f"episode:{episode.episode_number}",
                )
            )
            continue
        for scene in snapshot.scenes:
            if scene.episode_id != episode.id:
                continue
            if scene.scene_number in parsed_scene_numbers:
                continue
            for shot in snapshot.shots:
                if shot.scene_id == scene.id:
                    operations.append(
                        ProposalItemInput(
                            command="story.delete_shot",
                            payload={
                                "episode_number": episode.episode_number,
                                "scene_number": scene.scene_number,
                                "shot_number": shot.shot_number,
                                "action": "delete",
                                "idempotency_key": idempotency_key,
                            },
                            expected_target_version=shot.version,
                            rationale="脚本草稿不再包含该 Shot",
                            action="delete",
                            key=f"shot:{episode.episode_number}.{scene.scene_number}.{shot.shot_number}",
                        )
                    )
            operations.append(
                ProposalItemInput(
                    command="story.delete_scene",
                    payload={
                        "episode_number": episode.episode_number,
                        "scene_number": scene.scene_number,
                        "action": "delete",
                        "idempotency_key": idempotency_key,
                    },
                    expected_target_version=scene.version,
                    rationale="脚本草稿不再包含该 Scene",
                    action="delete",
                    key=f"scene:{episode.episode_number}.{scene.scene_number}",
                )
            )

    if document is None or document.content_hash != content_hash:
        operations.append(
            ProposalItemInput(
                command="story.set_script_document",
                payload={
                    "filename": filename[:260],
                    "content_hash": content_hash,
                    "raw_text": raw_text,
                    "format": "md" if filename.lower().endswith(".md") else "txt",
                    "brief": brief[:8000],
                    "action": "create" if document is None else "update",
                    "idempotency_key": idempotency_key,
                },
                expected_target_version=None,
                rationale="记录已采用的故事草稿原文",
                action="create" if document is None else "update",
                key="script_document",
            )
        )

    target_episode = snapshot.episode_by_number(parsed.episode_number)
    operations.append(
        ProposalItemInput(
            command="story.upsert_episode",
            payload={
                "episode_number": parsed.episode_number,
                "title": parsed.title,
                "synopsis": parsed.synopsis,
                "action": "update" if target_episode is not None else "create",
                "idempotency_key": idempotency_key,
            },
            expected_target_version=(
                target_episode.version if target_episode is not None else None
            ),
            rationale="脚本草稿的 Episode 结构",
            action="update" if target_episode is not None else "create",
            key=f"episode:{parsed.episode_number}",
        )
    )

    global_sort = 0
    for parsed_scene in parsed.scenes:
        existing_scene = (
            snapshot.scene_by_episode_number(
                target_episode, parsed_scene.scene_number
            )
            if target_episode is not None
            else None
        )
        operations.append(
            ProposalItemInput(
                command="story.upsert_scene",
                payload={
                    "episode_number": parsed.episode_number,
                    "scene_number": parsed_scene.scene_number,
                    "location_name": parsed_scene.location_name,
                    "time_of_day": parsed_scene.time_of_day,
                    "synopsis": parsed_scene.synopsis,
                    "action": "update" if existing_scene is not None else "create",
                    "idempotency_key": idempotency_key,
                },
                expected_target_version=(
                    existing_scene.version if existing_scene is not None else None
                ),
                rationale="脚本草稿的 Scene 结构",
                action="update" if existing_scene is not None else "create",
                key=f"scene:{parsed.episode_number}.{parsed_scene.scene_number}",
            )
        )
        for parsed_shot in parsed_scene.shots:
            global_sort += 1
            existing_shot = (
                snapshot.shot_by_scene(existing_scene, parsed_shot.shot_number)
                if existing_scene is not None
                else None
            )
            operations.append(
                ProposalItemInput(
                    command="story.upsert_shot",
                    payload=_shot_payload(
                        episode_number=parsed.episode_number,
                        scene_number=parsed_scene.scene_number,
                        shot_number=parsed_shot.shot_number,
                        shot_type=parsed_shot.shot_type,
                        camera_move=parsed_shot.camera_move,
                        visual_description=parsed_shot.visual,
                        dialogue=parsed_shot.dialogue,
                        duration_seconds=parsed_shot.duration_seconds,
                        sort_order=global_sort,
                        idempotency_key=idempotency_key,
                        action="update" if existing_shot is not None else "create",
                    ),
                    expected_target_version=(
                        existing_shot.version if existing_shot is not None else None
                    ),
                    rationale="脚本草稿的 Shot 结构",
                    action="update" if existing_shot is not None else "create",
                    key=(
                        f"shot:{parsed.episode_number}.{parsed_scene.scene_number}."
                        f"{parsed_shot.shot_number}"
                    ),
                )
            )
    return operations


def _operation_dict(item: ProposalItemInput) -> dict[str, object]:
    return {
        "item_ref": item.key,
        "command": item.command,
        "action": item.action,
        "expected_target_version": item.expected_target_version,
        "proposed": item.payload,
        "rationale": item.rationale,
    }


async def create_story_proposal(
    session: AsyncSession,
    *,
    project_id: UUID,
    actor: User,
    brief: str,
    filename: str,
    draft_text: str,
    idempotency_key: str,
) -> StoryProposalResult:
    """Persist one typed Story proposal without mutating canonical Story rows."""

    if not draft_text.strip():
        raise ValidationAppError(
            "story draft text is required",
            details={"code": "STORY_DRAFT_REQUIRED"},
        )

    existing = await _find_by_idempotency_key(
        session,
        project_id=project_id,
        idempotency_key=idempotency_key,
    )
    if existing is not None:
        existing_proposal, existing_items = existing
        operations = [
            _operation_dict(
                ProposalItemInput(
                    command=item.command,
                    payload=dict(item.payload or {}),
                    expected_target_version=item.expected_target_version,
                    rationale=item.rationale,
                    action=str((item.payload or {}).get("action") or "create"),
                    key=str((item.payload or {}).get("key") or item.command),
                )
            )
            for item in existing_items
        ]
        return StoryProposalResult(
            proposal=existing_proposal,
            items=list(existing_items),
            operations=operations,
        )

    parsed = parse_script_markdown(draft_text)
    snapshot = await _load_snapshot(session, project_id=project_id)
    document = await _latest_document(session, project_id=project_id)
    content_hash = hashlib.sha256(draft_text.encode("utf-8")).hexdigest()
    operation_inputs = _build_operations(
        snapshot=snapshot,
        parsed=parsed,
        document=document,
        content_hash=content_hash,
        filename=filename,
        raw_text=draft_text,
        brief=brief,
        idempotency_key=idempotency_key,
    )
    if not operation_inputs:
        raise ValidationAppError(
            "story draft matches the current canonical story",
            details={"code": "STORY_PROPOSAL_NO_DIFF"},
        )

    thread = await _get_or_create_project_thread(
        session,
        project_id=project_id,
        actor=actor,
    )
    if brief.strip():
        session.add(
            DirectorMessage(
                thread_id=thread.id,
                project_id=project_id,
                role="user",
                content=brief[:8000],
                created_by=actor.id,
            )
        )
    proposal = DirectorProposal(
        project_id=project_id,
        thread_id=thread.id,
        scope_type="project",
        scope_entity_id=project_id,
        status="pending",
        created_by=actor.id,
    )
    session.add(proposal)
    await session.flush()

    items: list[DirectorProposalItem] = []
    for sort_order, op in enumerate(operation_inputs):
        payload = dict(op.payload)
        payload["key"] = op.key
        payload["sort_order"] = sort_order
        item = DirectorProposalItem(
            proposal_id=proposal.id,
            project_id=project_id,
            command=op.command,
            payload=payload,
            expected_target_version=op.expected_target_version,
            rationale=op.rationale or "",
            benefit="按脚本草稿结构更新 Canonical Story",
            cost="仅修改被用户接受的 Scene/Shot/Episode 结构",
    risk=(
        "结构变化可能影响已绑定的镜头与制作事实；"
        "删除带正式媒体/执行记录的 Shot 会 fail closed"
    ),
            impact=op.key,
            status="pending",
        )
        session.add(item)
        items.append(item)
    await session.flush()
    operations = [_operation_dict(op) for op in operation_inputs]
    return StoryProposalResult(
        proposal=proposal,
        items=items,
        operations=operations,
    )


async def _find_by_idempotency_key(
    session: AsyncSession,
    *,
    project_id: UUID,
    idempotency_key: str,
) -> tuple[DirectorProposal, list[DirectorProposalItem]] | None:
    """Small-project scan of project-scope Director proposals for a key."""

    proposals = list(
        (
            await session.execute(
                select(DirectorProposal)
                .where(
                    DirectorProposal.project_id == project_id,
                    DirectorProposal.scope_type == "project",
                    DirectorProposal.scope_entity_id == project_id,
                )
                .order_by(DirectorProposal.created_at, DirectorProposal.id)
            )
        )
        .scalars()
        .all()
    )
    for proposal in proposals:
        items = list(
            (
                await session.execute(
                    select(DirectorProposalItem)
                    .where(DirectorProposalItem.proposal_id == proposal.id)
                    .order_by(DirectorProposalItem.created_at, DirectorProposalItem.id)
                )
            )
            .scalars()
            .all()
        )
        if any(
            str((item.payload or {}).get("idempotency_key") or "") == idempotency_key
            for item in items
        ):
            return proposal, items
    return None


__all__ = [
    "ProposalItemInput",
    "StoryProposalResult",
    "create_story_proposal",
]
