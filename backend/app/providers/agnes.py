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
import hashlib
import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from uuid import uuid4

import httpx

from app.config import Settings, get_settings


class AgnesHubClient:
    _IMAGE_MAX_ATTEMPTS = 8
    _IMAGE_REQUEST_TIMEOUT_S = 150.0
    _IMAGE_RETRYABLE_STATUSES = {408, 429, 500, 502, 503, 504}
    _IMAGE_BACKOFF_CAP_S = 20.0
    _VIDEO_MAX_ATTEMPTS = 8
    _VIDEO_REQUEST_TIMEOUT_S = 120.0
    _VIDEO_BACKOFF_CAP_S = 90.0

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._transport = transport
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

    @staticmethod
    def _policy_safe_image_prompt(prompt: str) -> str:
        """Keep a storyboard beat while removing physical-confrontation wording.

        This is only used after the provider explicitly rejects an image request.
        The original plan remains on the NodeRun; callers receive fingerprints for
        both requests so the adaptation is visible in ProviderOperation audit data.
        """
        rewritten = prompt
        replacements = (
            (r"\bstalker(?:'s)?\b", "unidentified figure"),
            (r"\bgrabbing\b", "reaching toward"),
            (r"\bgrabs\b", "reaches toward"),
            (r"\bgrab\b", "reach toward"),
            (r"\bslipping to reveal\b", "partially opened to reveal"),
            (r"\bfreeze frame, then black screen\b", "a dramatic cinematic pause"),
        )
        for pattern, replacement in replacements:
            rewritten = re.sub(pattern, replacement, rewritten, flags=re.IGNORECASE)
        return rewritten + ", non-violent cinematic suspense, no physical confrontation"

    @staticmethod
    def _is_image_policy_refusal(data: object) -> bool:
        message = str(data).lower()
        return any(
            marker in message
            for marker in (
                "unable to generate this content",
                "content policy",
                "safety policy",
                "modify your prompt",
            )
        )

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
        original_fingerprint = hashlib.sha256(prompt.encode()).hexdigest()
        effective_prompt = prompt
        policy_rewrite = False
        last_err = "unknown"
        # Eight 150-second requests plus capped backoff fit inside the heavy
        # Worker's 30-minute execution budget.
        async with httpx.AsyncClient(
            timeout=self._IMAGE_REQUEST_TIMEOUT_S,
            transport=self._transport,
        ) as client:
            for attempt in range(1, self._IMAGE_MAX_ATTEMPTS + 1):
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
                            "prompt_adaptation": (
                                "provider_policy_safe_rewrite" if policy_rewrite else None
                            ),
                            "original_prompt_fingerprint": original_fingerprint,
                            "effective_prompt_fingerprint": hashlib.sha256(
                                effective_prompt.encode()
                            ).hexdigest(),
                        }
                    last_err = f"agnes image http {resp.status_code}: {str(data)[:120]}"
                    if (
                        resp.status_code == 400
                        and not policy_rewrite
                        and self._is_image_policy_refusal(data)
                    ):
                        effective_prompt = self._policy_safe_image_prompt(prompt)
                        body["prompt"] = effective_prompt
                        policy_rewrite = True
                        continue
                    if resp.status_code in self._IMAGE_RETRYABLE_STATUSES:
                        await asyncio.sleep(self._image_retry_delay(attempt))
                        continue
                except (
                    httpx.TimeoutException,
                    httpx.NetworkError,
                    httpx.RemoteProtocolError,
                ) as exc:
                    last_err = f"{type(exc).__name__}: {exc}"
                    await asyncio.sleep(self._image_retry_delay(attempt))
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
                "prompt_adaptation": (
                    "provider_policy_safe_rewrite" if policy_rewrite else None
                ),
                "original_prompt_fingerprint": original_fingerprint,
                "effective_prompt_fingerprint": hashlib.sha256(
                    effective_prompt.encode()
                ).hexdigest(),
            }

    @classmethod
    def _image_retry_delay(cls, attempt: int) -> float:
        return min(2.0**attempt, cls._IMAGE_BACKOFF_CAP_S)

    @classmethod
    def _video_retry_delay(cls, response: httpx.Response, attempt: int) -> float:
        """Honor the hub cooldown when it supplies one for a rejected create."""
        retry_after = response.headers.get("Retry-After", "").strip()
        if retry_after:
            try:
                return min(max(float(retry_after), 0.0), cls._VIDEO_BACKOFF_CAP_S)
            except ValueError:
                try:
                    delay = (
                        parsedate_to_datetime(retry_after) - datetime.now(UTC)
                    ).total_seconds()
                    return min(max(delay, 0.0), cls._VIDEO_BACKOFF_CAP_S)
                except (TypeError, ValueError):
                    pass
        return min(15.0 * 2.0 ** (attempt - 1), cls._VIDEO_BACKOFF_CAP_S)

    async def create_video(self, *, prompt: str) -> dict[str, Any]:
        """POST /videos — async task creation."""
        if not self.configured():
            raise RuntimeError("Agnes hub not configured (AGNES_ENABLED + AGNES_API_KEY)")
        url = f"{self._base}/videos"
        body = {"model": self._video_model, "prompt": prompt}
        last_err = "unknown"
        async with httpx.AsyncClient(
            timeout=self._VIDEO_REQUEST_TIMEOUT_S,
            transport=self._transport,
        ) as client:
            for attempt in range(1, self._VIDEO_MAX_ATTEMPTS + 1):
                try:
                    resp = await client.post(url, headers=self._headers(), json=body)
                    try:
                        data = resp.json()
                    except Exception:
                        data = {"raw_status": resp.status_code}
                    task_id = None
                    if isinstance(data, dict):
                        task_id = (
                            data.get("task_id")
                            or data.get("video_id")
                            or data.get("id")
                        )
                    if resp.status_code < 400 and task_id:
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
                    last_err = f"agnes video http {resp.status_code}: {str(data)[:200]}"
                    if resp.status_code in self._IMAGE_RETRYABLE_STATUSES:
                        await asyncio.sleep(self._video_retry_delay(resp, attempt))
                        continue
                except (
                    httpx.TimeoutException,
                    httpx.NetworkError,
                    httpx.RemoteProtocolError,
                ) as exc:
                    last_err = f"{type(exc).__name__}: {exc}"
                    await asyncio.sleep(self._image_retry_delay(attempt))
                    continue
                break
        return {
            "remote_task_id": str(uuid4()),
            "status": "failed",
            "error": last_err[:300],
        }

    async def poll_video(self, remote_task_id: str) -> dict[str, Any]:
        """GET /videos/{id} for async video tasks."""
        if not self.configured():
            raise RuntimeError("Agnes hub not configured")
        url = f"{self._base}/videos/{remote_task_id}"
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.get(url, headers=self._headers())
        except (
            httpx.TimeoutException,
            httpx.NetworkError,
            httpx.RemoteProtocolError,
        ) as exc:
            # A poll failure is not a task failure. The Worker retains the same
            # remote task id and retries polling within its bounded job window.
            return {"status": "running", "poll_error": type(exc).__name__}
        else:
            try:
                raw_data = resp.json()
            except Exception:
                raw_data = {"raw_status": resp.status_code}
            data: dict[str, Any] = raw_data if isinstance(raw_data, dict) else {}
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
            uri: object | None = None
            meta = data.get("metadata")
            if isinstance(meta, dict):
                uri = meta.get("url") or meta.get("video_url")
            output = data.get("output")
            if isinstance(output, dict):
                uri = uri or output.get("url")
            elif isinstance(output, str):
                uri = uri or output
            uri = uri or data.get("url") or data.get("video_url")
            nested_data = data.get("data")
            if isinstance(nested_data, dict):
                uri = uri or nested_data.get("url")
            self._tasks[remote_task_id] = {
                "kind": "video",
                "status": status,
                "artifact_uri": uri,
                "error": data.get("error"),
            }
            raw_progress = data.get("progress", 0)
            progress = (
                float(raw_progress) / 100.0
                if isinstance(raw_progress, int | float) and raw_progress > 1
                else float(raw_progress or 0)
            )
            result: dict[str, Any] = {
                "status": status,
                "progress": progress,
            }
            if uri:
                result["artifact_uri"] = uri
            if status == "failed":
                result["error"] = str(data.get("error", data))[:300]
            return result

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
