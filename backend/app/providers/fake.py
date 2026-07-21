"""In-process fake Adapters for local product path (no paid BYOK)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4


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
            text = (
                '{"prompt":"Cinematic neon rain keyframe 9:16, lead silhouette",'
                '"shot_notes":"wide establishing"}'
            )
        else:
            text = (
                '{"logline":"A heroine faces neon rain and a shadow stalker.",'
                '"tone":"cinematic","audience":"short-drama"}'
            )
        if "Return ONLY" not in prompt and not prompt:
            text = str(request.get("prompt") or text)
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
                digest = __import__("hashlib").sha256(prompt.encode()).digest()
                img = Image.new(
                    "RGB",
                    (64, 64),
                    color=(digest[0], digest[1], digest[2]),
                )
                draw = ImageDraw.Draw(img)
                draw.rectangle([4, 4, 60, 60], outline=(digest[3], digest[4], digest[5]), width=2)
                # Scatter unique pixels from digest
                for i in range(16):
                    img.putpixel((8 + (i % 8) * 6, 8 + (i // 8) * 24), (digest[i], digest[i], 255 - digest[i]))
                buf = BytesIO()
                img.save(buf, format="PNG")
                return buf.getvalue()
            except Exception:
                return b"\x89PNG\r\n\x1a\n" + prompt.encode()
        if kind in {"video", "video_review", "composite"}:
            # Fake MP4-ish payload (not a real container; FFmpeg may fail → fail-closed)
            return b"\x00\x00\x00\x18ftypmp42" + prompt.encode() + b"\x00" * 64
        if kind in {"voice"}:
            # Minimal RIFF/WAV header + silence payload
            return b"RIFF$\x00\x00\x00WAVEfmt " + prompt.encode()[:16].ljust(16, b"\0")
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
