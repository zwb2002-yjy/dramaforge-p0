"""In-process fake Adapters for local product path (no paid BYOK)."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import uuid4


def _fixture_text(value: object, *, fallback: str) -> str:
    text = " ".join(str(value or "").split())
    return text[:240] or fallback


def _request_context(request: dict[str, Any]) -> dict[str, Any]:
    raw = request.get("brief")
    return raw if isinstance(raw, dict) else {}


def build_fake_brief(idea: object) -> dict[str, object]:
    """Produce an input-derived valid Brief for APP_ENV=test only."""
    premise = _fixture_text(idea, fallback="A protagonist confronts a difficult choice.")
    return {
        "title": f"Draft: {premise[:72]}",
        "logline": f"A protagonist acts on the central premise: {premise}",
        "synopsis": (
            f"Starting from the premise '{premise}', the protagonist identifies an urgent "
            "problem, makes an imperfect plan, and faces escalating resistance. Each choice "
            "reveals a new consequence until the final beat forces a decisive next step."
        ),
        "protagonist": {
            "name": "The lead",
            "profile": "A capable person whose perspective shapes the story.",
            "goal": "Resolve the central problem before its consequences become irreversible.",
        },
        "conflict": "Opposition and incomplete information make every next action costly.",
        "stakes": "Failure changes the lead's future and leaves the central problem unresolved.",
        "world": f"A grounded story world shaped by this premise: {premise}",
        "tone": "focused dramatic tension with emotional clarity",
        "audience": "vertical short-drama viewers",
        "visual_style": "cinematic contrast, motivated practical light, readable 9:16 composition",
        "episode_hook": "The final discovery reframes the lead's next decision.",
    }


def build_fake_plan(brief: object) -> dict[str, object]:
    """Produce ten input-derived structured Shots for APP_ENV=test only."""
    brief_body = brief if isinstance(brief, dict) else {}
    logline = _fixture_text(
        brief_body.get("logline"),
        fallback=_fixture_text(brief, fallback="A protagonist confronts a difficult choice."),
    )
    title = _fixture_text(brief_body.get("title"), fallback="Generated episode")
    world = _fixture_text(brief_body.get("world"), fallback="the story setting")
    protagonist_raw = brief_body.get("protagonist")
    protagonist = protagonist_raw if isinstance(protagonist_raw, dict) else {}
    lead = _fixture_text(protagonist.get("name"), fallback="the lead")
    shots: list[dict[str, object]] = []
    shot_types = ("wide", "medium", "close", "over_shoulder", "insert")
    camera_moves = ("static", "push_in", "tracking", "pan", "handheld")
    for number in range(1, 11):
        scene_number = 1 if number <= 5 else 2
        location = "the initial setting" if scene_number == 1 else "the pressure point"
        story_beat = (
            "establishes the situation"
            if number == 1
            else "ends on the unresolved turn"
            if number == 10
            else "advances the consequence of the previous choice"
        )
        shots.append(
            {
                "shot_number": number,
                "scene_number": scene_number,
                "location": location,
                "time_of_day": "story time",
                "shot_type": shot_types[(number - 1) % len(shot_types)],
                "camera_move": camera_moves[(number - 1) % len(camera_moves)],
                "visual_description": (
                    f"Shot {number}: {lead} {story_beat} in {location}; composition makes "
                    f"the premise '{logline}' readable."
                ),
                "dialogue": "" if number % 2 else f"Beat {number} clarifies the next choice.",
                "keyframe_prompt": (
                    f"9:16 cinematic short drama, shot {number}, {lead}, {location}, "
                    f"story premise: {logline}, setting: {world}, clear action, "
                    "consistent appearance, motivated lighting"
                ),
                "lead_identity_required": number not in {5, 10},
                "duration_seconds": 3.0,
            }
        )
    return {
        "title": f"{title} - Episode 1",
        "episode_summary": logline,
        "visual_bible": {
            "aspect_ratio": "9:16",
            "style": _fixture_text(
                brief_body.get("visual_style"),
                fallback="cinematic vertical drama",
            ),
            "color_palette": "story-appropriate contrast with readable skin tones",
            "lighting": "motivated practical light that supports the story beat",
            "character_continuity": f"{lead} retains a consistent appearance across all shots",
            "negative_prompt": "deformed face, extra fingers, text, watermark",
        },
        "shots": shots,
    }


def build_fake_concept_set(request: dict[str, Any]) -> dict[str, object]:
    context = _request_context(request)
    seed = _fixture_text(
        context.get("idea")
        or context.get("script_text")
        or request.get("idea")
        or request.get("prompt"),
        fallback="一次迟到的坦白改变了两个人的关系",
    )
    concepts = []
    for index, angle in enumerate(("误会", "选择", "反转"), start=1):
        concepts.append(
            {
                "concept_id": f"concept-{index}",
                "title": f"{angle}：{seed[:24]}",
                "logline": f"围绕“{seed}”，两个人在一次{angle}中被迫说出真心。",
                "theme": "坦诚需要付出代价",
                "character_relationship": "彼此在意却不愿先示弱的两个人",
                "core_conflict": f"主角必须在失去关系前解决{angle}带来的冲突",
                "ending_direction": "最后一句对白改变双方对这段关系的理解",
                "why_it_fits": "可以在15至30秒内用少量角色和对白形成闭环",
            }
        )
    return {
        "entry_mode": context.get("entry_mode") or "one_sentence",
        "creation_goal": context.get("creation_goal"),
        "adaptation_mode": context.get("adaptation_mode"),
        "source_rights_confirmed": bool(context.get("source_rights_confirmed")),
        "preference_summary": _fixture_text(context.get("preference_summary"), fallback=""),
        "concepts": concepts,
    }


def build_fake_preference(request: dict[str, Any]) -> dict[str, object]:
    context = _request_context(request)
    feedback = _fixture_text(
        context.get("feedback") or request.get("feedback"),
        fallback="保留情感冲突，减少套路",
    )
    return {
        "liked": [feedback],
        "disliked": [],
        "inferred_preferences": ["重视人物动机和真实情绪"],
        "avoid": ["没有铺垫的反转"],
        "interpretation_summary": f"理解为：{feedback}",
    }


def build_fake_creative_package(request: dict[str, Any]) -> dict[str, object]:
    context = _request_context(request)
    selected = str(context.get("selected_concept_id") or "concept-1")
    theme = _fixture_text(context.get("theme"), fallback="坦诚需要勇气")
    conflict = _fixture_text(context.get("core_conflict"), fallback="两人必须解开误会")
    emotional = _fixture_text(context.get("emotional_direction"), fallback="克制后释然")
    ending = _fixture_text(context.get("ending"), fallback="两人决定重新开始")
    return {
        "story_core": {
            "selected_concept_id": selected,
            "theme": theme,
            "core_conflict": conflict,
            "emotional_direction": emotional,
            "ending": ending,
            "characters": [
                {
                    "name": "林夏",
                    "identity": "准备离开这座城市的年轻设计师",
                    "desire": "在离开前听到对方的真实答案",
                    "fear_or_cost": "先开口意味着承认自己一直在等待",
                },
                {
                    "name": "程野",
                    "identity": "习惯用沉默回避感情的摄影师",
                    "desire": "挽回关系却害怕再次伤害对方",
                    "fear_or_cost": "继续沉默就会永远失去林夏",
                },
            ],
        },
        "episode_script": {
            "title": f"短剧 {selected}",
            "target_duration_seconds": 24,
            "setup": "林夏拖着行李在门口，程野终于赶到。",
            "turn": "程野承认那封拒绝信并不是他的真实决定。",
            "ending": ending,
            "dialogue": [
                {"speaker": "林夏", "text": "你还是来晚了。", "emotion": "克制"},
                {"speaker": "程野", "text": "这次我不想再让你猜。", "emotion": "坚定"},
                {"speaker": "林夏", "text": "那就说完。", "emotion": emotional},
            ],
        },
    }


def build_fake_story_review(_request: dict[str, Any]) -> dict[str, object]:
    return {
        "status": "passed",
        "logic_issues": [],
        "pacing_issues": [],
        "duration_risks": [],
        "closure_issues": [],
        "revision_suggestions": [],
    }


def _fake_story_characters(request: dict[str, Any]) -> list[dict[str, Any]]:
    context = _request_context(request)
    story = context.get("story_core")
    if isinstance(story, dict) and isinstance(story.get("characters"), list):
        return [item for item in story["characters"] if isinstance(item, dict)]
    return [{"name": "Lin Xia", "identity": "designer"}]


def build_fake_character_bible(request: dict[str, Any]) -> dict[str, object]:
    characters = []
    for index, item in enumerate(_fake_story_characters(request), start=1):
        name = _fixture_text(item.get("name"), fallback=f"Character {index}")
        characters.append(
            {
                "character_id": f"character-{index}",
                "name": name,
                "age_range": "25-32",
                "facial_features": f"Distinct oval face and expressive eyes for {name}",
                "hair": "natural dark hair with a stable silhouette",
                "body_shape": "average adult build",
                "wardrobe": f"locked contemporary wardrobe for {name}",
                "distinguishing_features": [f"unique silhouette {index}"],
                "locked_prompt": f"fictional adult {name}, stable face, stable hair and wardrobe",
                "negative_prompt": "real celebrity, identity drift, duplicate person",
            }
        )
    return {
        "policy": "fictional_characters_only",
        "real_person_reference_allowed": False,
        "characters": characters,
    }


def build_fake_visual_bible(request: dict[str, Any]) -> dict[str, object]:
    context = _request_context(request)
    return {
        "medium": "photorealistic_live_action",
        "aspect_ratio": context.get("aspect_ratio") or "9:16",
        "era_and_setting": "contemporary grounded interior",
        "color_palette": "restrained neutral tones with warm skin tones",
        "lighting": "motivated soft practical light",
        "lens_language": "stable eye-level singles and restrained close-ups",
        "continuity_rules": [
            "keep wardrobe unchanged",
            "preserve screen direction",
            "keep lighting direction stable",
        ],
        "preview_is_generated_media": False,
    }


def build_fake_voice_bible(request: dict[str, Any]) -> dict[str, object]:
    voices = []
    for index, item in enumerate(_fake_story_characters(request), start=1):
        name = _fixture_text(item.get("name"), fallback=f"Character {index}")
        voices.append(
            {
                "character_id": f"character-{index}",
                "character_name": name,
                "voice_description": f"fictional Mandarin voice {index}, clear and grounded",
                "pace": "medium",
                "emotional_range": ["restrained", "honest"],
                "voice_clone": False,
            }
        )
    return {"language": "zh-CN", "voice_clone_allowed": False, "voices": voices}


def build_fake_storyboard(request: dict[str, Any]) -> dict[str, object]:
    context = _request_context(request)
    script = context.get("episode_script")
    script_body = script if isinstance(script, dict) else {}
    raw_dialogue = script_body.get("dialogue")
    dialogue = (
        [item for item in raw_dialogue if isinstance(item, dict)]
        if isinstance(raw_dialogue, list)
        else []
    )
    story_characters = _fake_story_characters(request)
    names = [_fixture_text(item.get("name"), fallback="Lead") for item in story_characters]
    duration = int(script_body.get("target_duration_seconds") or 24)
    shot_count = 3
    base = duration // shot_count
    durations = [base] * shot_count
    durations[-1] += duration - sum(durations)
    buckets: list[list[dict[str, Any]]] = [[] for _ in range(shot_count)]
    for index, line in enumerate(dialogue):
        buckets[min(index + 1, shot_count - 1)].append(line)
    shots = []
    for index in range(shot_count):
        shot_number = index + 1
        shot_names = names[:2] if index == 1 and len(names) > 1 else [names[index % len(names)]]
        shots.append(
            {
                "shot_id": f"shot-{shot_number}",
                "shot_number": shot_number,
                "duration_seconds": durations[index],
                "location": "apartment doorway",
                "time_of_day": "evening",
                "shot_type": "over_shoulder" if len(shot_names) > 1 else "medium_close",
                "camera_move": "static",
                "characters": shot_names,
                "action": f"story beat {shot_number} advances the locked conflict",
                "dialogue": buckets[index],
                "image_prompt": f"photorealistic locked fictional character, shot {shot_number}",
                "video_prompt": f"restrained natural performance, shot {shot_number}",
                "transition": "motivated straight cut",
            }
        )
    return {
        "template_key": "live_action_dialogue_short_v1",
        "aspect_ratio": context.get("aspect_ratio") or "9:16",
        "target_duration_seconds": duration,
        "shots": shots,
    }


class FakeOpenAIAdapter:
    provider = "openai"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._tasks: dict[str, dict[str, Any]] = {}

    async def create(self, request: dict[str, Any]) -> dict[str, Any]:
        self.calls.append({"op": "create", "request": request})
        task_id = f"fake-openai-{uuid4()}"
        kind = str(request.get("kind") or "brief")
        prompt = str(request.get("prompt") or "")
        if kind == "concept_set":
            text = json.dumps(build_fake_concept_set(request), ensure_ascii=False)
        elif kind == "preference_understanding":
            text = json.dumps(build_fake_preference(request), ensure_ascii=False)
        elif kind == "creative_story":
            text = json.dumps(build_fake_creative_package(request), ensure_ascii=False)
        elif kind == "story_review":
            text = json.dumps(build_fake_story_review(request), ensure_ascii=False)
        elif kind == "shooting_character_visual":
            text = json.dumps(build_fake_character_bible(request), ensure_ascii=False)
        elif kind == "shooting_visual":
            text = json.dumps(build_fake_visual_bible(request), ensure_ascii=False)
        elif kind == "shooting_voice":
            text = json.dumps(build_fake_voice_bible(request), ensure_ascii=False)
        elif kind == "shooting_storyboard":
            text = json.dumps(build_fake_storyboard(request), ensure_ascii=False)
        elif kind == "plan":
            text = json.dumps(
                build_fake_plan(request.get("brief") or request.get("idea") or prompt),
                ensure_ascii=False,
            )
        else:
            text = json.dumps(
                build_fake_brief(request.get("idea") or prompt),
                ensure_ascii=False,
            )
        self._tasks[task_id] = {"status": "succeeded", "text": text}
        return {"remote_task_id": task_id, "status": "succeeded", "text": text}

    async def poll(self, remote_task_id: str) -> dict[str, Any]:
        task = self._tasks.get(remote_task_id)
        if task is None:
            return {"status": "failed", "error": "unknown task"}
        return {"status": task["status"], "progress": 1.0, "text": task.get("text")}

    async def cancel(self, remote_task_id: str) -> dict[str, Any]:
        if remote_task_id in self._tasks:
            self._tasks[remote_task_id]["status"] = "cancelled"
        return {"status": "cancelled"}

    async def fetch_cost(self, remote_task_id: str) -> dict[str, Any]:
        _ = remote_task_id
        return {"amount": 0.0, "currency": "USD", "units": 0.0}


class FakeFluxAdapter:
    """Image/video/voice/subtitle media factory — content depends on prompt+kind."""

    provider = "flux"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._tasks: dict[str, dict[str, Any]] = {}
        self.blobs: dict[str, bytes] = {}

    async def create(self, request: dict[str, Any]) -> dict[str, Any]:
        self.calls.append({"op": "create", "request": request})
        task_id = f"fake-flux-{uuid4()}"
        kind = str(request.get("kind", "keyframe"))
        prompt = str(request.get("prompt", "frame"))
        blob = self._blob_for(kind, prompt)
        self.blobs[task_id] = blob
        self._tasks[task_id] = {
            "status": "succeeded",
            "artifact_uri": f"minio://fake/{task_id}",
            "content_hash": "a" * 64,
            "kind": kind,
        }
        return {"remote_task_id": task_id, "status": "succeeded"}

    def _blob_for(self, kind: str, prompt: str) -> bytes:
        # Minimal PNG for image-like kinds so PIL can decode embeddings
        if kind in {
            "keyframe",
            "identity_review",
            "image",
            "prompt",
            "prompt_compose",
        }:
            try:
                from io import BytesIO

                from PIL import Image, ImageDraw

                # Prompt-dependent color so embeddings differ by content
                # Full prompt hash drives RGB so unique prompts ⇒ unique PNG bytes
                digest = hashlib.sha256(prompt.encode()).digest()
                img = Image.new(
                    "RGB",
                    (64, 64),
                    color=(digest[0], digest[1], digest[2]),
                )
                draw = ImageDraw.Draw(img)
                draw.rectangle([4, 4, 60, 60], outline=(digest[3], digest[4], digest[5]), width=2)
                # Scatter unique pixels from digest
                for i in range(16):
                    img.putpixel(
                        (8 + (i % 8) * 6, 8 + (i // 8) * 24),
                        (digest[i], digest[i], 255 - digest[i]),
                    )
                buf = BytesIO()
                img.save(buf, format="PNG")
                return buf.getvalue()
            except Exception:
                return b"\x89PNG\r\n\x1a\n" + prompt.encode()
        if kind in {"video", "video_review", "composite"}:
            # Fake MP4-ish payload (not a real container; FFmpeg may fail → fail-closed)
            return b"\x00\x00\x00\x18ftypmp42" + prompt.encode() + b"\x00" * 64
        if kind in {"voice"}:
            # Keep the test-only WAV-shaped bytes prompt-specific. Truncating
            # the common "9:16 cinematic..." prefix caused every shot's
            # synthetic voice to hash identically and masked artifact reuse.
            digest = hashlib.sha256(prompt.encode()).digest()
            return b"RIFF$\x00\x00\x00WAVEfmt " + digest
        if kind in {"subtitle"}:
            return f"1\n00:00:00,000 --> 00:00:01,000\n{prompt}\n".encode()
        if kind in {"continuity_review"}:
            return f'{{"prompt":"{prompt}","ok":true}}'.encode()
        return f"{kind}:{prompt}".encode()

    async def poll(self, remote_task_id: str) -> dict[str, Any]:
        task = self._tasks.get(remote_task_id)
        if task is None:
            return {"status": "failed", "error": "unknown task"}
        return {
            "status": task["status"],
            "progress": 1.0,
            "artifact_uri": task.get("artifact_uri"),
            "content_hash": task.get("content_hash"),
        }

    async def cancel(self, remote_task_id: str) -> dict[str, Any]:
        if remote_task_id in self._tasks:
            self._tasks[remote_task_id]["status"] = "cancelled"
        return {"status": "cancelled"}

    async def fetch_cost(self, remote_task_id: str) -> dict[str, Any]:
        _ = remote_task_id
        return {"amount": 0.0, "currency": "USD", "units": 1.0}
