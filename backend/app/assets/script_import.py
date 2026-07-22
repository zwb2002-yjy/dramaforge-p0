"""Import UTF-8 .txt/.md scripts into Episode / Scene / Shot rows (P0-02 / §3.1.8)."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import User
from app.access.projects import ProjectService
from app.assets.models import Episode, Scene, ScriptDocument, Shot
from app.shared.errors import ValidationAppError

_SCENE_RE = re.compile(
    r"^##\s*Scene\s+(\d+)\s*[—\-–:]\s*(.+?)(?:\s*/\s*(.+))?\s*$",
    re.IGNORECASE,
)
_SHOT_RE = re.compile(
    r"^###\s*Shot\s+(\d+)\s*[—\-–:]\s*(.+)$",
    re.IGNORECASE,
)
_EPISODE_RE = re.compile(r"^#\s*Episode\s+(\d+)\s*[—\-–:]\s*(.+)$", re.IGNORECASE)
_CHAR_RE = re.compile(r"^Lead:\s*(.+)$", re.IGNORECASE)


@dataclass(frozen=True)
class ParsedShot:
    shot_number: int
    shot_type: str
    visual: str
    dialogue: str
    camera_move: str = "static"
    duration_seconds: Decimal = Decimal("3")


@dataclass(frozen=True)
class ParsedScene:
    scene_number: int
    location_name: str
    time_of_day: str
    synopsis: str
    shots: list[ParsedShot]


@dataclass(frozen=True)
class ParsedScript:
    episode_number: int
    title: str
    synopsis: str
    lead_character: str | None
    scenes: list[ParsedScene]


@dataclass(frozen=True)
class ImportResult:
    script_document_id: UUID
    episode_id: UUID
    scene_count: int
    shot_count: int
    shot_ids: list[UUID]
    lead_character: str | None
    content_hash: str


def parse_script_markdown(text: str) -> ParsedScript:
    """Parse a simple markdown script fixture into episodes/scenes/shots.

    Expected shape (fixtures/scripts/p0_10_shots.md):
      # Episode 1 — Title
      Lead: Hero Name
      ## Scene 1 — Location / night
      synopsis...
      ### Shot 1 — medium
      Visual: ...
      Dialogue: ...
    """
    if not text or not text.strip():
        raise ValidationAppError("empty script")
    lines = text.replace("\r\n", "\n").split("\n")
    episode_number = 1
    title = "Untitled"
    synopsis_parts: list[str] = []
    lead: str | None = None
    scenes: list[ParsedScene] = []
    cur_scene: dict[str, Any] | None = None
    cur_shot: dict[str, Any] | None = None

    def flush_shot() -> None:
        nonlocal cur_shot, cur_scene
        if cur_shot is None or cur_scene is None:
            return
        cur_scene["shots"].append(
            ParsedShot(
                shot_number=int(cur_shot["shot_number"]),
                shot_type=str(cur_shot.get("shot_type") or "medium"),
                visual=str(cur_shot.get("visual") or "").strip() or "visual pending",
                dialogue=str(cur_shot.get("dialogue") or "").strip(),
                camera_move=str(cur_shot.get("camera_move") or "static"),
            )
        )
        cur_shot = None

    def flush_scene() -> None:
        nonlocal cur_scene
        flush_shot()
        if cur_scene is None:
            return
        scenes.append(
            ParsedScene(
                scene_number=int(cur_scene["scene_number"]),
                location_name=str(cur_scene["location_name"]),
                time_of_day=str(cur_scene["time_of_day"]),
                synopsis=str(cur_scene.get("synopsis") or ""),
                shots=list(cur_scene["shots"]),
            )
        )
        cur_scene = None

    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            continue
        m_ep = _EPISODE_RE.match(line)
        if m_ep:
            flush_scene()
            episode_number = int(m_ep.group(1))
            title = m_ep.group(2).strip()
            continue
        m_char = _CHAR_RE.match(line.strip())
        if m_char:
            lead = m_char.group(1).strip()
            continue
        m_sc = _SCENE_RE.match(line)
        if m_sc:
            flush_scene()
            loc = m_sc.group(2).strip()
            tod = (m_sc.group(3) or "day").strip()
            cur_scene = {
                "scene_number": int(m_sc.group(1)),
                "location_name": loc,
                "time_of_day": tod,
                "synopsis": "",
                "shots": [],
            }
            continue
        m_sh = _SHOT_RE.match(line)
        if m_sh:
            flush_shot()
            cur_shot = {
                "shot_number": int(m_sh.group(1)),
                "shot_type": m_sh.group(2).strip() or "medium",
                "visual": "",
                "dialogue": "",
                "camera_move": "static",
            }
            continue
        low = line.strip()
        if cur_shot is not None:
            if low.lower().startswith("visual:"):
                cur_shot["visual"] = low.split(":", 1)[1].strip()
            elif low.lower().startswith("dialogue:"):
                cur_shot["dialogue"] = low.split(":", 1)[1].strip()
            elif low.lower().startswith("camera:"):
                cur_shot["camera_move"] = low.split(":", 1)[1].strip()
            elif not cur_shot["visual"]:
                cur_shot["visual"] = low
            else:
                cur_shot["dialogue"] = (cur_shot.get("dialogue") or "") + (" " + low)
            continue
        if cur_scene is not None and not str(cur_scene.get("synopsis") or ""):
            cur_scene["synopsis"] = low
            continue
        synopsis_parts.append(low)

    flush_scene()
    if not scenes:
        raise ValidationAppError("script has no scenes")
    total_shots = sum(len(s.shots) for s in scenes)
    if total_shots == 0:
        raise ValidationAppError("script has no shots")
    return ParsedScript(
        episode_number=episode_number,
        title=title,
        synopsis=" ".join(synopsis_parts).strip(),
        lead_character=lead,
        scenes=scenes,
    )


async def import_script(
    session: AsyncSession,
    *,
    project_id: UUID,
    actor_id: UUID,
    filename: str,
    text: str,
    actor: User | None = None,
) -> ImportResult:
    """Persist ScriptDocument + Episode + Scenes + Shots under project membership."""
    if actor is not None:
        await ProjectService(session).get_project_for_member(project_id=project_id, actor=actor)
    parsed = parse_script_markdown(text)
    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    existing_doc = (
        await session.execute(
            select(ScriptDocument)
            .where(ScriptDocument.project_id == project_id)
            .where(ScriptDocument.content_hash == content_hash)
            .order_by(ScriptDocument.created_at, ScriptDocument.id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing_doc is not None:
        existing_episode = (
            await session.execute(
                select(Episode).where(
                    Episode.project_id == project_id,
                    Episode.episode_number == parsed.episode_number,
                )
            )
        ).scalar_one_or_none()
        if existing_episode is None:
            raise ValidationAppError(
                "existing script import is incomplete",
                details={"code": "SCRIPT_IMPORT_INCOMPLETE"},
            )
        existing_scenes = list(
            (
                await session.execute(
                    select(Scene)
                    .where(Scene.episode_id == existing_episode.id)
                    .order_by(Scene.scene_number, Scene.id)
                )
            )
            .scalars()
            .all()
        )
        scenes_by_number = {scene.scene_number: scene for scene in existing_scenes}
        existing_shots = list(
            (
                await session.execute(
                    select(Shot)
                    .where(Shot.project_id == project_id)
                    .where(Shot.scene_id.in_([scene.id for scene in existing_scenes]))
                    .order_by(Shot.sort_order, Shot.shot_number, Shot.id)
                )
            )
            .scalars()
            .all()
        )
        shots_by_scene_number = {
            (shot.scene_id, shot.shot_number): shot for shot in existing_shots
        }
        expected_shot_count = sum(len(scene.shots) for scene in parsed.scenes)
        ordered_shots: list[Shot] = []
        for parsed_scene in parsed.scenes:
            scene = scenes_by_number.get(parsed_scene.scene_number)
            if scene is None:
                continue
            for parsed_shot in parsed_scene.shots:
                shot = shots_by_scene_number.get((scene.id, parsed_shot.shot_number))
                if shot is not None:
                    ordered_shots.append(shot)
        if (
            len(ordered_shots) != expected_shot_count
            or len({shot.id for shot in ordered_shots}) != expected_shot_count
        ):
            raise ValidationAppError(
                "existing script import is incomplete",
                details={
                    "code": "SCRIPT_IMPORT_INCOMPLETE",
                    "expected_scene_count": len(parsed.scenes),
                    "actual_scene_count": len(existing_scenes),
                    "expected_shot_count": expected_shot_count,
                    "actual_shot_count": len(ordered_shots),
                },
            )
        return ImportResult(
            script_document_id=existing_doc.id,
            episode_id=existing_episode.id,
            scene_count=len(parsed.scenes),
            shot_count=len(ordered_shots),
            shot_ids=[shot.id for shot in ordered_shots],
            lead_character=parsed.lead_character,
            content_hash=content_hash,
        )

    fmt = "md" if filename.lower().endswith(".md") else "txt"
    doc = ScriptDocument(
        project_id=project_id,
        filename=filename[:260],
        content_hash=content_hash,
        raw_text=text,
        format=fmt,
        imported_by=actor_id,
    )
    session.add(doc)
    await session.flush()

    # Upsert episode by number
    existing = (
        await session.execute(
            select(Episode).where(
                Episode.project_id == project_id,
                Episode.episode_number == parsed.episode_number,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        ep = Episode(
            project_id=project_id,
            episode_number=parsed.episode_number,
            title=parsed.title,
            synopsis=parsed.synopsis,
        )
        session.add(ep)
        await session.flush()
    else:
        ep = existing
        ep.title = parsed.title
        ep.synopsis = parsed.synopsis
        ep.version += 1
        await session.flush()

    existing_scenes = list(
        (
            await session.execute(
                select(Scene)
                .where(Scene.episode_id == ep.id)
                .order_by(Scene.scene_number, Scene.id)
            )
        )
        .scalars()
        .all()
    )
    scenes_by_number = {scene.scene_number: scene for scene in existing_scenes}
    existing_shots = list(
        (
            await session.execute(
                select(Shot)
                .where(Shot.project_id == project_id)
                .where(Shot.scene_id.in_([scene.id for scene in existing_scenes]))
                .order_by(Shot.sort_order, Shot.shot_number, Shot.id)
            )
        )
        .scalars()
        .all()
    )
    shots_by_scene_number = {
        (shot.scene_id, shot.shot_number): shot for shot in existing_shots
    }
    shots_by_number: dict[int, Shot | None] = {}
    for shot in existing_shots:
        if shot.shot_number in shots_by_number:
            shots_by_number[shot.shot_number] = None
        else:
            shots_by_number[shot.shot_number] = shot

    shot_ids: list[UUID] = []
    assigned_shot_ids: set[UUID] = set()
    global_order = 0
    for sc in parsed.scenes:
        scene = scenes_by_number.get(sc.scene_number)
        if scene is None:
            scene = Scene(
                episode_id=ep.id,
                scene_number=sc.scene_number,
                location_name=sc.location_name,
                time_of_day=sc.time_of_day,
                synopsis=sc.synopsis,
            )
            session.add(scene)
            await session.flush()
            scenes_by_number[sc.scene_number] = scene
        else:
            scene.location_name = sc.location_name
            scene.time_of_day = sc.time_of_day
            scene.synopsis = sc.synopsis
            scene.version += 1
        for sh in sc.shots:
            global_order += 1
            shot = shots_by_scene_number.get((scene.id, sh.shot_number))
            if shot is None or shot.id in assigned_shot_ids:
                by_number = shots_by_number.get(sh.shot_number)
                if by_number is not None and by_number.id not in assigned_shot_ids:
                    shot = by_number
            if shot is None or shot.id in assigned_shot_ids:
                shot = Shot(
                    project_id=project_id,
                    scene_id=scene.id,
                    shot_number=sh.shot_number,
                    shot_type=sh.shot_type,
                    camera_move=sh.camera_move,
                    visual_description=sh.visual,
                    dialogue=sh.dialogue,
                    duration_seconds=sh.duration_seconds,
                    status="draft",
                    sort_order=global_order,
                )
                session.add(shot)
                await session.flush()
            else:
                shot.scene_id = scene.id
                shot.shot_number = sh.shot_number
                shot.shot_type = sh.shot_type
                shot.camera_move = sh.camera_move
                shot.visual_description = sh.visual
                shot.dialogue = sh.dialogue
                shot.duration_seconds = sh.duration_seconds
                shot.sort_order = global_order
                shot.version += 1
            assigned_shot_ids.add(shot.id)
            shot_ids.append(shot.id)

    await session.flush()
    return ImportResult(
        script_document_id=doc.id,
        episode_id=ep.id,
        scene_count=len(parsed.scenes),
        shot_count=len(shot_ids),
        shot_ids=shot_ids,
        lead_character=parsed.lead_character,
        content_hash=content_hash,
    )
