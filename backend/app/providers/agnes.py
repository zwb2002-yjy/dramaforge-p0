"""Agnes AI OpenAI-compatible hub client (image + video).

Real endpoints verified against apihub.agnes-ai.com:
  GET  /v1/models
  POST /v1/images/generations  -> { data: [{ url }] }
  POST /v1/videos              -> { id/task_id, status: queued|... }
  GET  /v1/videos/{task_id}    -> poll status / result

Never logs the full API key.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

import httpx

from app.config import Settings, get_settings


class AgnesHubClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._base = self._settings.agnes_base_url.rstrip("/")
        self._key = self._settings.agnes_api_key.strip()
        self._image_model = self._settings.agnes_image_model
        self._video_model = self._settings.agnes_video_model
        self._tasks: dict[str, dict[str, Any]] = {}

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
        }

    def configured(self) -> bool:
        return bool(self._key and self._settings.agnes_enabled)

    async def create_image(self, *, prompt: str, size: str = "1024x1024") -> dict[str, Any]:
        if not self.configured():
            raise RuntimeError("Agnes hub not configured (AGNES_ENABLED + AGNES_API_KEY)")
        remote_id = f"agnes-img-{uuid4()}"
        url = f"{self._base}/images/generations"
        body = {
            "model": self._image_model,
            "prompt": prompt,
            "n": 1,
            "size": size,
        }
        last_err = "unknown"
        # Free hub can return 503 / disconnect mid-body; retry with backoff.
        async with httpx.AsyncClient(timeout=300.0) as client:
            for attempt in range(1, 6):
                try:
                    resp = await client.post(url, headers=self._headers(), json=body)
                    try:
                        data = resp.json()
                    except Exception:
                        data = {"raw_status": resp.status_code}
                    ok = resp.status_code < 400
                    image_url = None
                    if isinstance(data, dict):
                        items = data.get("data")
                        if isinstance(items, list) and items:
                            first = items[0]
                            if isinstance(first, dict):
                                image_url = first.get("url") or first.get("b64_json")
                    if ok and image_url:
                        self._tasks[remote_id] = {
                            "kind": "image",
                            "status": "succeeded",
                            "http_status": resp.status_code,
                            "artifact_uri": image_url,
                            "error": None,
                        }
                        return {
                            "remote_task_id": remote_id,
                            "status": "succeeded",
                            "artifact_uri": image_url,
                        }
                    last_err = f"agnes image http {resp.status_code}: {str(data)[:120]}"
                    # Retry transient hub overload
                    if resp.status_code in {408, 429, 500, 502, 503, 504}:
                        await asyncio.sleep(2.0 * attempt)
                        continue
                except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
                    last_err = f"{type(exc).__name__}: {exc}"
                    await asyncio.sleep(2.0 * attempt)
                    continue
                break
            self._tasks[remote_id] = {
                "kind": "image",
                "status": "failed",
                "artifact_uri": None,
                "error": last_err[:300],
            }
            return {
                "remote_task_id": remote_id,
                "status": "failed",
                "error": last_err[:300],
            }

    async def create_video(self, *, prompt: str) -> dict[str, Any]:
        """POST /videos — async task creation."""
        if not self.configured():
            raise RuntimeError("Agnes hub not configured (AGNES_ENABLED + AGNES_API_KEY)")
        url = f"{self._base}/videos"
        body = {"model": self._video_model, "prompt": prompt}
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, headers=self._headers(), json=body)
            try:
                data = resp.json()
            except Exception:
                data = {"raw_status": resp.status_code}
            ok = resp.status_code < 400
            task_id = None
            if isinstance(data, dict):
                task_id = (
                    data.get("task_id")
                    or data.get("video_id")
                    or data.get("id")
                )
            if not ok or not task_id:
                return {
                    "remote_task_id": str(task_id or uuid4()),
                    "status": "failed",
                    "error": f"agnes video http {resp.status_code}: {str(data)[:200]}",
                }
            remote_id = str(task_id)
            self._tasks[remote_id] = {
                "kind": "video",
                "status": str(data.get("status", "queued")),
                "http_status": resp.status_code,
                "artifact_uri": None,
                "error": None,
            }
            return {
                "remote_task_id": remote_id,
                "status": str(data.get("status", "queued")),
            }

    async def poll_video(self, remote_task_id: str) -> dict[str, Any]:
        """GET /videos/{id} for async video tasks."""
        if not self.configured():
            raise RuntimeError("Agnes hub not configured")
        url = f"{self._base}/videos/{remote_task_id}"
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(url, headers=self._headers())
            try:
                data = resp.json()
            except Exception:
                data = {"raw_status": resp.status_code}
            if resp.status_code >= 400:
                return {"status": "failed", "error": f"poll http {resp.status_code}"}
            status = str(data.get("status", "unknown"))
            # Normalize completed variants
            if status in {"succeeded", "completed", "success", "done"}:
                status = "succeeded"
            elif status in {"failed", "error"}:
                status = "failed"
            elif status in {"queued", "pending", "processing", "running", "in_progress"}:
                status = "running" if status != "queued" else "queued"
            uri = None
            if isinstance(data, dict):
                meta = data.get("metadata")
                if isinstance(meta, dict):
                    uri = meta.get("url") or meta.get("video_url")
                out = data.get("output")
                if isinstance(out, dict):
                    uri = uri or out.get("url")
                elif isinstance(out, str):
                    uri = uri or out
                uri = uri or data.get("url") or data.get("video_url")
                if isinstance(data.get("data"), dict):
                    uri = uri or data["data"].get("url")
            self._tasks[remote_task_id] = {
                "kind": "video",
                "status": status,
                "artifact_uri": uri,
                "error": data.get("error") if isinstance(data, dict) else None,
            }
            out: dict[str, Any] = {
                "status": status,
                "progress": float(data.get("progress", 0) or 0) / 100.0
                if isinstance(data.get("progress"), (int, float)) and data.get("progress", 0) > 1
                else float(data.get("progress", 0) or 0),
            }
            if uri:
                out["artifact_uri"] = uri
            if status == "failed":
                out["error"] = str(data.get("error", data))[:300]
            return out

    async def poll(self, remote_task_id: str) -> dict[str, Any]:
        task = self._tasks.get(remote_task_id)
        if task and task.get("kind") == "video":
            return await self.poll_video(remote_task_id)
        if task is None:
            # try video poll anyway
            if remote_task_id.startswith("task_") or remote_task_id.startswith("agnes-vid"):
                return await self.poll_video(remote_task_id)
            return {"status": "failed", "error": "unknown task"}
        return {
            "status": task["status"],
            "progress": 1.0 if task["status"] == "succeeded" else 0.0,
            "artifact_uri": task.get("artifact_uri"),
            "error": task.get("error"),
        }

    async def wait_video(
        self, remote_task_id: str, *, timeout_s: float = 300.0, interval_s: float = 3.0
    ) -> dict[str, Any]:
        deadline = asyncio.get_event_loop().time() + timeout_s
        last: dict[str, Any] = {"status": "queued"}
        while asyncio.get_event_loop().time() < deadline:
            last = await self.poll_video(remote_task_id)
            if last.get("status") in {"succeeded", "failed", "cancelled"}:
                return last
            await asyncio.sleep(interval_s)
        last["status"] = "failed"
        last["error"] = "timeout waiting for video"
        return last

    async def cancel(self, remote_task_id: str) -> dict[str, Any]:
        if remote_task_id in self._tasks:
            self._tasks[remote_task_id]["status"] = "cancelled"
        return {"status": "cancelled"}

    async def fetch_cost(self, remote_task_id: str) -> dict[str, Any]:
        _ = remote_task_id
        return {"amount": 0.0, "currency": "USD", "units": 1.0}


class AgnesImageAdapter:
    provider = "flux"

    def __init__(self, settings: Settings | None = None) -> None:
        self._client = AgnesHubClient(settings)

    async def create(self, request: dict[str, Any]) -> dict[str, Any]:
        prompt = str(request.get("prompt", ""))
        return await self._client.create_image(prompt=prompt)

    async def poll(self, remote_task_id: str) -> dict[str, Any]:
        return await self._client.poll(remote_task_id)

    async def cancel(self, remote_task_id: str) -> dict[str, Any]:
        return await self._client.cancel(remote_task_id)

    async def fetch_cost(self, remote_task_id: str) -> dict[str, Any]:
        return await self._client.fetch_cost(remote_task_id)


class AgnesVideoAdapter:
    provider = "kling"

    def __init__(self, settings: Settings | None = None) -> None:
        self._client = AgnesHubClient(settings)

    async def create(self, request: dict[str, Any]) -> dict[str, Any]:
        prompt = str(request.get("prompt", ""))
        return await self._client.create_video(prompt=prompt)

    async def poll(self, remote_task_id: str) -> dict[str, Any]:
        return await self._client.poll(remote_task_id)

    async def cancel(self, remote_task_id: str) -> dict[str, Any]:
        return await self._client.cancel(remote_task_id)

    async def fetch_cost(self, remote_task_id: str) -> dict[str, Any]:
        return await self._client.fetch_cost(remote_task_id)
