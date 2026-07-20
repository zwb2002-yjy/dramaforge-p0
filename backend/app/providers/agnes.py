"""Agnes AI OpenAI-compatible hub client (image + video).

Used as local BYOK transport. Domain Adapter names stay flux/kling at the edge;
this module is the HTTP implementation when AGNES_* env is configured.
Never logs the full API key.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx

from app.config import Settings, get_settings


class AgnesHubClient:
    """Thin httpx client for Agnes OpenAI-compatible endpoints."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        base = self._settings.agnes_base_url.rstrip("/")
        self._base = base
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
        """POST /images/generations (OpenAI-compatible). Falls back to task bookkeeping."""
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
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, headers=self._headers(), json=body)
            # Store status without full response dumps in logs
            data: dict[str, Any]
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
            self._tasks[remote_id] = {
                "kind": "image",
                "status": "succeeded" if ok else "failed",
                "http_status": resp.status_code,
                "artifact_uri": image_url or f"agnes://image/{remote_id}",
                "error": None if ok else str(data)[:200],
            }
            if not ok:
                return {
                    "remote_task_id": remote_id,
                    "status": "failed",
                    "error": f"agnes image http {resp.status_code}",
                }
            return {"remote_task_id": remote_id, "status": "succeeded"}

    async def create_video(self, *, prompt: str) -> dict[str, Any]:
        """Best-effort video create; hub paths vary — records remote task for poll."""
        if not self.configured():
            raise RuntimeError("Agnes hub not configured (AGNES_ENABLED + AGNES_API_KEY)")
        remote_id = f"agnes-vid-{uuid4()}"
        # Common OpenAI-compatible video paths; try video generations style endpoint.
        url = f"{self._base}/videos/generations"
        body = {"model": self._video_model, "prompt": prompt}
        async with httpx.AsyncClient(timeout=180.0) as client:
            resp = await client.post(url, headers=self._headers(), json=body)
            try:
                data = resp.json()
            except Exception:
                data = {"raw_status": resp.status_code}
            ok = resp.status_code < 400
            self._tasks[remote_id] = {
                "kind": "video",
                "status": "succeeded" if ok else "failed",
                "http_status": resp.status_code,
                "artifact_uri": f"agnes://video/{remote_id}",
                "error": None if ok else str(data)[:200],
            }
            if not ok:
                return {
                    "remote_task_id": remote_id,
                    "status": "failed",
                    "error": f"agnes video http {resp.status_code}",
                }
            return {"remote_task_id": remote_id, "status": "succeeded"}

    async def poll(self, remote_task_id: str) -> dict[str, Any]:
        task = self._tasks.get(remote_task_id)
        if task is None:
            return {"status": "failed", "error": "unknown task"}
        return {
            "status": task["status"],
            "progress": 1.0 if task["status"] == "succeeded" else 0.0,
            "artifact_uri": task.get("artifact_uri"),
            "error": task.get("error"),
        }

    async def cancel(self, remote_task_id: str) -> dict[str, Any]:
        if remote_task_id in self._tasks:
            self._tasks[remote_task_id]["status"] = "cancelled"
        return {"status": "cancelled"}

    async def fetch_cost(self, remote_task_id: str) -> dict[str, Any]:
        _ = remote_task_id
        return {"amount": 0.0, "currency": "USD", "units": 1.0}


class AgnesImageAdapter:
    """Image Adapter surface (maps to domain flux capability when configured)."""

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
    """Video Adapter surface (maps to domain kling capability when configured)."""

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
