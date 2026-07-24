"""In-process fake Adapters for local product path (no paid BYOK)."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import uuid4


def _fixture_text(value: object, *, fallback: str) -> str:
    text = " ".join(str(value or "").split())
    return text[:240] or fallback


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
        if kind == "plan":
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
            "face_review",
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
