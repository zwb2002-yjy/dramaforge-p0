"""Agnes China ``agnes_cn_v1`` image and video protocol profile.

The profile owns every wire path. Provider Connection hosts therefore stay at
``https://api.agnes-ai.cn`` and never include ``/v1``. Paid create requests are
single-attempt: transport ambiguity is returned as ``unknown_submission`` so a
caller cannot accidentally hide a duplicate POST inside the adapter.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Literal, cast
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from pydantic import JsonValue

from app.config import Settings, get_settings

AGNES_CN_PROFILE = "agnes_cn_v1"
AGNES_CN_HOST = "https://api.agnes-ai.cn"
AGNES_IMAGE_PATH = "/v1/images/generations"
AGNES_VIDEO_CREATE_PATH = "/v1/videos"
AGNES_VIDEO_BY_ID_PATH = "/agnesapi"
_ALLOWED_REFERENCE_MIMES = frozenset({"image/png", "image/jpeg", "image/webp"})
_MAX_REFERENCE_BYTES = 20 * 1024 * 1024


def normalize_agnes_host(value: str) -> str:
    """Normalize a legacy ``.../v1`` setting into a profile-independent host."""
    raw = value.strip().rstrip("/")
    if raw.endswith("/v1"):
        raw = raw[:-3]
    parsed = urlsplit(raw)
    if parsed.scheme != "https" or not parsed.hostname or parsed.query or parsed.fragment:
        raise ValueError("Agnes host must be an HTTPS origin")
    if parsed.path not in {"", "/"}:
        raise ValueError("Agnes host must not contain a path")
    return f"https://{parsed.netloc}"


def _require_prompt(prompt: str) -> str:
    value = prompt.strip()
    if not value:
        raise ValueError("prompt must be non-empty")
    return value


def _reference_data_uri(*, data: bytes, mime_type: str) -> tuple[str, str]:
    mime = mime_type.strip().lower()
    if mime not in _ALLOWED_REFERENCE_MIMES:
        raise ValueError("canonical image MIME is not allowed")
    if not data or len(data) > _MAX_REFERENCE_BYTES:
        raise ValueError("canonical image byte size is invalid")
    fingerprint = hashlib.sha256(data).hexdigest()
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{encoded}", fingerprint


def _require_https_reference(value: str) -> str:
    reference = value.strip()
    parsed = urlsplit(reference)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("video reference must be a public HTTPS URL")
    return reference


def _validate_video_shape(*, num_frames: int, frame_rate: int) -> None:
    if num_frames < 1 or num_frames > 441 or (num_frames - 1) % 8 != 0:
        raise ValueError("num_frames must be <= 441 and satisfy 8n + 1")
    if frame_rate < 1 or frame_rate > 60:
        raise ValueError("frame_rate must be between 1 and 60")


def _schema_fingerprint(body: dict[str, object]) -> str:
    """Fingerprint field shape while replacing prompts, references, and tokens."""

    def redacted(value: object, key: str = "") -> object:
        if key == "prompt":
            return "<prompt>"
        if key in {"image", "url", "video_url"}:
            if isinstance(value, list):
                return ["<reference>" for _ in value]
            return "<reference>"
        if isinstance(value, dict):
            return {str(k): redacted(v, str(k)) for k, v in sorted(value.items())}
        if isinstance(value, list):
            return [redacted(item) for item in value]
        return value

    raw = json.dumps(redacted(body), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _error_code(status_code: int) -> str:
    if status_code == 400:
        return "PROVIDER_BAD_REQUEST"
    if status_code == 401:
        return "PROVIDER_AUTH_FAILED"
    if status_code == 403:
        return "PROVIDER_FORBIDDEN"
    if status_code == 429:
        return "PROVIDER_RATE_LIMITED"
    if status_code >= 500:
        return "PROVIDER_UNAVAILABLE"
    return "PROVIDER_REQUEST_FAILED"


def _retry_after_seconds(response: httpx.Response) -> float | None:
    retry_after = response.headers.get("Retry-After", "").strip()
    if not retry_after:
        return None
    try:
        return max(float(retry_after), 0.0)
    except ValueError:
        try:
            return max(
                (parsedate_to_datetime(retry_after) - datetime.now(UTC)).total_seconds(),
                0.0,
            )
        except (TypeError, ValueError):
            return None


def _json_object(response: httpx.Response) -> dict[str, Any]:
    try:
        value = response.json()
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _image_result_url(data: dict[str, Any]) -> str | None:
    items = data.get("data")
    if not isinstance(items, list) or not items or not isinstance(items[0], dict):
        return None
    value = items[0].get("url")
    return str(value) if isinstance(value, str) and value else None


def _video_result_url(data: dict[str, Any]) -> str | None:
    """Migration parser until an account-verified China response fixture is frozen."""
    candidates: list[object] = [data.get("url"), data.get("video_url")]
    for key in ("data", "output", "metadata"):
        nested = data.get(key)
        if isinstance(nested, dict):
            candidates.extend((nested.get("url"), nested.get("video_url")))
        elif key == "output":
            candidates.append(nested)
    for candidate in candidates:
        if isinstance(candidate, str) and candidate:
            return candidate
    return None


# ---------------------------------------------------------------------------
# Low-level transport and wire-body builders (single source of truth).
# Both the legacy HubClient methods and the unified Compiler/Runtime go through
# these, so there is exactly one wire contract and one HTTP send path.
# ---------------------------------------------------------------------------


async def _post_json(
    host: str,
    path: str,
    *,
    headers: dict[str, str],
    body: dict[str, object],
    timeout: float,
    transport: httpx.AsyncBaseTransport | None,
) -> httpx.Response:
    async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
        return await client.post(f"{host}{path}", headers=headers, json=body)


async def _get_json(
    host: str,
    path: str,
    *,
    headers: dict[str, str],
    params: dict[str, str] | None,
    timeout: float,
    transport: httpx.AsyncBaseTransport | None,
) -> httpx.Response:
    async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
        return await client.get(f"{host}{path}", headers=headers, params=params)


def _build_image_body(
    model: str,
    *,
    prompt: str,
    size: str,
    canonical_image_bytes: bytes | None = None,
    canonical_image_mime: str = "image/png",
) -> tuple[dict[str, object], str, list[str]]:
    """Construct the Image 2.x request body and derive operation + fingerprints."""
    prompt_value = _require_prompt(prompt)
    size_value = size.strip()
    if not size_value:
        raise ValueError("size must be non-empty")
    extra_body: dict[str, object] = {"response_format": "url"}
    reference_fingerprints: list[str] = []
    if canonical_image_bytes is not None:
        data_uri, fingerprint = _reference_data_uri(
            data=canonical_image_bytes,
            mime_type=canonical_image_mime,
        )
        extra_body["image"] = [data_uri]
        reference_fingerprints.append(fingerprint)
    body: dict[str, object] = {
        "model": model,
        "prompt": prompt_value,
        "size": size_value,
        "extra_body": extra_body,
    }
    operation = "image.i2i" if reference_fingerprints else "image.t2i"
    return body, operation, reference_fingerprints


def _build_video_body(
    model: str,
    *,
    prompt: str,
    image_url: str | None = None,
    image_bytes: bytes | None = None,
    image_mime: str = "image/png",
    num_frames: int = 121,
    frame_rate: int = 24,
    keyframe_urls: list[str] | None = None,
) -> tuple[dict[str, object], str, list[str], str]:
    """Construct the Video V2.0 request body and derive operation/transport."""
    prompt_value = _require_prompt(prompt)
    _validate_video_shape(num_frames=num_frames, frame_rate=frame_rate)
    if image_url and keyframe_urls:
        raise ValueError("first-frame I2V and keyframes mode are mutually exclusive")
    if image_bytes is not None and (image_url or keyframe_urls):
        raise ValueError("image_bytes cannot be combined with image_url/keyframe_urls")
    body: dict[str, object] = {
        "model": model,
        "prompt": prompt_value,
        "num_frames": num_frames,
        "frame_rate": frame_rate,
        "height": 1280,
        "width": 720,
    }
    operation = "video.i2v"
    reference_transport = "short_lived_https"
    references: list[str]
    if keyframe_urls is not None:
        if len(keyframe_urls) != 2:
            raise ValueError("keyframes mode requires exactly two HTTPS images")
        references = [_require_https_reference(item) for item in keyframe_urls]
        body["extra_body"] = {"image": references, "mode": "keyframes"}
        operation = "video.keyframes"
    elif image_url is not None:
        references = [_require_https_reference(image_url)]
        body["image"] = references[0]
    elif image_bytes is not None:
        encoded = base64.b64encode(image_bytes).decode("ascii")
        body["image"] = encoded
        references = [encoded]
        reference_transport = "base64_raw"
    else:
        raise ValueError("video I2V requires one first-frame reference")
    return body, operation, references, reference_transport


def _request_fingerprint(body: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


class AgnesHubClient:
    """Single-attempt Agnes China protocol client."""

    _IMAGE_REQUEST_TIMEOUT_S = 150.0
    _VIDEO_REQUEST_TIMEOUT_S = 120.0

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        host: str | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._transport = transport
        self._host = normalize_agnes_host(host or self._settings.agnes_base_url)
        self._key = self._settings.agnes_api_key.strip()
        self._image_model = self._settings.agnes_image_model
        self._video_model = self._settings.agnes_video_model
        self._tasks: dict[str, dict[str, Any]] = {}

    @property
    def host(self) -> str:
        return self._host

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
        }

    def configured(self) -> bool:
        return bool(self._key and self._settings.agnes_enabled)

    async def create_image(
        self,
        *,
        prompt: str,
        size: str = "1024x768",
        canonical_image_bytes: bytes | None = None,
        canonical_image_mime: str = "image/png",
        reference_artifact_id: str | None = None,
    ) -> dict[str, Any]:
        if not self.configured():
            raise RuntimeError("Agnes China connection is not configured")
        body, operation, reference_fingerprints = _build_image_body(
            self._image_model,
            prompt=prompt,
            size=size,
            canonical_image_bytes=canonical_image_bytes,
            canonical_image_mime=canonical_image_mime,
        )
        request_fingerprint = _request_fingerprint(body)
        summary: dict[str, object] = {
            "protocol_profile": AGNES_CN_PROFILE,
            "host": urlsplit(self._host).hostname or "",
            "operation": operation,
            "model": self._image_model,
            "size": str(body.get("size", "")),
            "reference_count": len(reference_fingerprints),
            "reference_artifact_ids": ([reference_artifact_id] if reference_artifact_id else []),
            "reference_fingerprints": reference_fingerprints,
            "reference_transport": "data_uri" if reference_fingerprints else "none",
            "request_schema_fingerprint": _schema_fingerprint(body),
        }
        try:
            response = await _post_json(
                self._host,
                AGNES_IMAGE_PATH,
                headers=self._headers(),
                body=body,
                timeout=self._IMAGE_REQUEST_TIMEOUT_S,
                transport=self._transport,
            )
        except httpx.TransportError as exc:
            return {
                "status": "unknown_submission",
                "error_code": "PROVIDER_SUBMISSION_UNKNOWN",
                "actual_provider": "agnes",
                "actual_model": self._image_model,
                "protocol_profile": AGNES_CN_PROFILE,
                "request_fingerprint": request_fingerprint,
                "request_summary": summary,
                "reference_fingerprints": reference_fingerprints,
                "transport_error": type(exc).__name__,
            }
        data = _json_object(response)
        image_url = _image_result_url(data)
        if response.status_code >= 400 or not image_url:
            code = (
                _error_code(response.status_code)
                if response.status_code >= 400
                else "PROVIDER_RESPONSE_INVALID"
            )
            return {
                "status": "failed",
                "http_status": response.status_code,
                "error_code": code,
                "error": f"Agnes image request failed ({response.status_code})",
                "retry_after_seconds": _retry_after_seconds(response),
                "actual_provider": "agnes",
                "actual_model": self._image_model,
                "protocol_profile": AGNES_CN_PROFILE,
                "request_fingerprint": request_fingerprint,
                "request_summary": summary,
                "reference_fingerprints": reference_fingerprints,
            }
        remote_id = f"agnes-image-{uuid4()}"
        self._tasks[remote_id] = {
            "kind": "image",
            "status": "succeeded",
            "artifact_uri": image_url,
        }
        return {
            "remote_task_id": remote_id,
            "status": "succeeded",
            "artifact_uri": image_url,
            "actual_provider": "agnes",
            "actual_model": self._image_model,
            "protocol_profile": AGNES_CN_PROFILE,
            "request_fingerprint": request_fingerprint,
            "request_summary": summary,
            "reference_fingerprints": reference_fingerprints,
        }

    async def create_video(
        self,
        *,
        prompt: str,
        image_url: str | None = None,
        image_bytes: bytes | None = None,
        image_mime: str = "image/png",
        num_frames: int = 121,
        frame_rate: int = 24,
        keyframe_urls: list[str] | None = None,
        reference_artifact_ids: list[str] | None = None,
        reference_fingerprints: list[str] | None = None,
    ) -> dict[str, Any]:
        if not self.configured():
            raise RuntimeError("Agnes China connection is not configured")
        body, operation, references, reference_transport = _build_video_body(
            self._video_model,
            prompt=prompt,
            image_url=image_url,
            image_bytes=image_bytes,
            image_mime=image_mime,
            num_frames=num_frames,
            frame_rate=frame_rate,
            keyframe_urls=keyframe_urls,
        )
        request_fingerprint = _request_fingerprint(body)
        summary: dict[str, object] = {
            "protocol_profile": AGNES_CN_PROFILE,
            "host": urlsplit(self._host).hostname or "",
            "operation": operation,
            "model": self._video_model,
            "num_frames": num_frames,
            "frame_rate": frame_rate,
            "reference_count": len(references),
            "reference_artifact_ids": list(reference_artifact_ids or []),
            "reference_fingerprints": list(reference_fingerprints or []),
            "reference_transport": reference_transport,
            "request_schema_fingerprint": _schema_fingerprint(body),
        }
        try:
            response = await _post_json(
                self._host,
                AGNES_VIDEO_CREATE_PATH,
                headers=self._headers(),
                body=body,
                timeout=self._VIDEO_REQUEST_TIMEOUT_S,
                transport=self._transport,
            )
        except httpx.TransportError as exc:
            return {
                "status": "unknown_submission",
                "error_code": "PROVIDER_SUBMISSION_UNKNOWN",
                "actual_provider": "agnes",
                "actual_model": self._video_model,
                "protocol_profile": AGNES_CN_PROFILE,
                "request_fingerprint": request_fingerprint,
                "request_summary": summary,
                "transport_error": type(exc).__name__,
            }
        data = _json_object(response)
        video_id = data.get("video_id")
        task_id = data.get("task_id")
        video_id_value = str(video_id) if video_id is not None and str(video_id) else None
        task_id_value = str(task_id) if task_id is not None and str(task_id) else None
        if response.status_code >= 400 or (video_id_value is None and task_id_value is None):
            code = (
                _error_code(response.status_code)
                if response.status_code >= 400
                else "PROVIDER_RESPONSE_INVALID"
            )
            return {
                "status": "failed",
                "http_status": response.status_code,
                "error_code": code,
                "error": f"Agnes video request failed ({response.status_code})",
                "retry_after_seconds": _retry_after_seconds(response),
                "actual_provider": "agnes",
                "actual_model": self._video_model,
                "protocol_profile": AGNES_CN_PROFILE,
                "request_fingerprint": request_fingerprint,
                "request_summary": summary,
            }
        remote_id = video_id_value or task_id_value
        assert remote_id is not None
        remote_secondary_id = task_id_value if video_id_value else None
        query_kind: Literal["video_id", "task_id"] = "video_id" if video_id_value else "task_id"
        self._tasks[remote_id] = {
            "kind": "video",
            "query_kind": query_kind,
            "remote_secondary_id": remote_secondary_id,
            "status": str(data.get("status") or "queued"),
        }
        return {
            "remote_task_id": remote_id,
            "remote_secondary_id": remote_secondary_id,
            "status": str(data.get("status") or "queued"),
            "actual_provider": "agnes",
            "actual_model": self._video_model,
            "protocol_profile": AGNES_CN_PROFILE,
            "request_fingerprint": request_fingerprint,
            "request_summary": summary,
            "query_kind": query_kind,
        }

    async def poll_video(
        self,
        remote_task_id: str,
        *,
        query_kind: Literal["video_id", "task_id"] | None = None,
    ) -> dict[str, Any]:
        if not self.configured():
            raise RuntimeError("Agnes China connection is not configured")
        task = self._tasks.get(remote_task_id, {})
        selected_kind = query_kind or task.get("query_kind")
        if selected_kind not in {"video_id", "task_id"}:
            raise ValueError("video poll query kind is required")
        if selected_kind == "video_id":
            path = AGNES_VIDEO_BY_ID_PATH
            params = {"video_id": remote_task_id}
        else:
            path = f"{AGNES_VIDEO_CREATE_PATH}/{remote_task_id}"
            params = None
        try:
            response = await _get_json(
                self._host,
                path,
                headers=self._headers(),
                params=params,
                timeout=60.0,
                transport=self._transport,
            )
        except httpx.TransportError as exc:
            return {
                "status": "running",
                "poll_error": type(exc).__name__,
                "error_code": "PROVIDER_POLL_TRANSIENT",
            }
        data = _json_object(response)
        if response.status_code >= 400:
            # Transient provider throttle/unavailability during polling must not
            # be terminal: the remote task already exists (plan §11.2). Keep the
            # poll alive on the same task; only genuine 4xx (bad task id, revoked
            # auth, permission) fail the node.
            if response.status_code == 429 or response.status_code >= 500:
                return {
                    "status": "running",
                    "http_status": response.status_code,
                    "error_code": (
                        "PROVIDER_RATE_LIMITED"
                        if response.status_code == 429
                        else "PROVIDER_POLL_TRANSIENT"
                    ),
                    "poll_error": f"http_{response.status_code}",
                    "retry_after_seconds": _retry_after_seconds(response),
                }
            return {
                "status": "failed",
                "http_status": response.status_code,
                "error_code": _error_code(response.status_code),
                "error": f"Agnes video poll failed ({response.status_code})",
            }
        raw_status = str(data.get("status") or "unknown").lower()
        if raw_status in {"succeeded", "completed", "success", "done"}:
            status = "succeeded"
        elif raw_status in {"failed", "error", "cancelled"}:
            status = "failed" if raw_status != "cancelled" else "cancelled"
        elif raw_status in {"queued", "pending"}:
            status = "queued"
        else:
            status = "running"
        uri = _video_result_url(data)
        raw_progress = data.get("progress", 0)
        try:
            progress = float(raw_progress or 0)
        except (TypeError, ValueError):
            progress = 0.0
        if progress > 1:
            progress /= 100.0
        result: dict[str, Any] = {"status": status, "progress": progress}
        if uri:
            result["artifact_uri"] = uri
        if status == "failed":
            result["error_code"] = "PROVIDER_TASK_FAILED"
            result["error"] = "Agnes video task failed"
        self._tasks[remote_task_id] = {**task, "kind": "video", "status": status}
        return result

    async def poll(self, remote_task_id: str) -> dict[str, Any]:
        task = self._tasks.get(remote_task_id)
        if task and task.get("kind") == "video":
            return await self.poll_video(remote_task_id)
        if task and task.get("kind") == "image":
            return {
                "status": task["status"],
                "progress": 1.0,
                "artifact_uri": task.get("artifact_uri"),
            }
        return {"status": "failed", "error_code": "PROVIDER_TASK_UNKNOWN"}

    async def wait_video(
        self,
        remote_task_id: str,
        *,
        timeout_s: float = 1_620.0,
        interval_s: float = 5.0,
    ) -> dict[str, Any]:
        deadline = asyncio.get_running_loop().time() + timeout_s
        last: dict[str, Any] = {"status": "queued"}
        while asyncio.get_running_loop().time() < deadline:
            last = await self.poll_video(remote_task_id)
            if last.get("status") in {"succeeded", "failed", "cancelled"}:
                return last
            await asyncio.sleep(interval_s)
        return {
            **last,
            "status": "running",
            "error_code": "PROVIDER_POLL_TRANSIENT",
            "poll_timeout": True,
        }

    async def cancel(self, remote_task_id: str) -> dict[str, Any]:
        if remote_task_id in self._tasks:
            self._tasks[remote_task_id]["status"] = "cancelled"
        return {"status": "cancelled"}

    async def fetch_cost(self, remote_task_id: str) -> dict[str, Any]:
        _ = remote_task_id
        return {"amount": 0.0, "currency": "USD", "units": 1.0}


class AgnesImageAdapter:
    provider = "agnes"
    protocol_profile = AGNES_CN_PROFILE
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        host: str | None = None,
    ) -> None:
        self._client = AgnesHubClient(settings, transport=transport, host=host)
        self.model = self._client._image_model

    async def create(self, request: dict[str, Any]) -> dict[str, Any]:
        image_bytes = request.get("canonical_image_bytes")
        if image_bytes is not None and not isinstance(image_bytes, bytes):
            raise TypeError("canonical_image_bytes must be bytes")
        return await self._client.create_image(
            prompt=str(request.get("prompt") or ""),
            size=str(request.get("size") or "1024x768"),
            canonical_image_bytes=image_bytes,
            canonical_image_mime=str(request.get("canonical_image_mime") or "image/png"),
            reference_artifact_id=(
                str(request["canonical_artifact_id"])
                if request.get("canonical_artifact_id")
                else None
            ),
        )

    async def poll(self, remote_task_id: str) -> dict[str, Any]:
        return await self._client.poll(remote_task_id)

    async def cancel(self, remote_task_id: str) -> dict[str, Any]:
        return await self._client.cancel(remote_task_id)

    async def fetch_cost(self, remote_task_id: str) -> dict[str, Any]:
        return await self._client.fetch_cost(remote_task_id)


class AgnesVideoAdapter:
    provider = "agnes"
    protocol_profile = AGNES_CN_PROFILE

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        host: str | None = None,
    ) -> None:
        self._client = AgnesHubClient(settings, transport=transport, host=host)
        self.model = self._client._video_model

    async def create(self, request: dict[str, Any]) -> dict[str, Any]:
        keyframe_urls = request.get("keyframe_urls")
        if keyframe_urls is not None and not isinstance(keyframe_urls, list):
            raise TypeError("keyframe_urls must be a list")
        return await self._client.create_video(
            prompt=str(request.get("prompt") or ""),
            image_url=(str(request["image_url"]) if request.get("image_url") else None),
            image_bytes=request.get("image_bytes"),
            image_mime=str(request.get("image_mime") or "image/png"),
            num_frames=int(request.get("num_frames", 121)),
            frame_rate=int(request.get("frame_rate", 24)),
            keyframe_urls=[str(item) for item in keyframe_urls] if keyframe_urls else None,
            reference_artifact_ids=[
                str(item) for item in request.get("reference_artifact_ids", [])
            ],
            reference_fingerprints=[
                str(item) for item in request.get("reference_fingerprints", [])
            ],
        )

    async def poll(self, remote_task_id: str) -> dict[str, Any]:
        return await self._client.poll(remote_task_id)

    async def poll_persisted(
        self,
        remote_task_id: str,
        *,
        query_kind: str | None,
    ) -> dict[str, Any]:
        if query_kind not in {"video_id", "task_id"}:
            raise ValueError("persisted Agnes video query kind is required")
        selected_kind: Literal["video_id", "task_id"] = (
            "video_id" if query_kind == "video_id" else "task_id"
        )
        return await self._client.poll_video(
            remote_task_id,
            query_kind=selected_kind,
        )

    async def cancel(self, remote_task_id: str) -> dict[str, Any]:
        return await self._client.cancel(remote_task_id)

    async def fetch_cost(self, remote_task_id: str) -> dict[str, Any]:
        return await self._client.fetch_cost(remote_task_id)


# ---------------------------------------------------------------------------
# Stage B2: unified Compiler + Runtime (single wire owner).
# Compilers validate against the catalog manifest and reuse the same body
# builders as the HubClient; the Runtime sends CompiledRequest.wire_request
# verbatim through the low-level transport.
# ---------------------------------------------------------------------------


def _compiled_summary(
    *,
    operation: str,
    invoke_model_value: str,
    reference_artifact_ids: list[str],
    reference_fingerprints: list[str],
    schema_version: str,
) -> dict[str, object]:
    return {
        "operation": operation,
        "model": invoke_model_value,
        "reference_artifact_ids": reference_artifact_ids,
        "reference_fingerprints": reference_fingerprints,
        "request_schema_version": schema_version,
    }


class AgnesImageCompiler:
    """Validates an image intent against the catalog manifest and compiles the
    wire request using the same body builder as :class:`AgnesHubClient`."""

    def validate(self, intent: Any, model: Any) -> None:
        op = model.operations.get("image.generate")
        if op is None:
            raise ValueError("model does not support image.generate")
        capabilities = set(op.capabilities)
        required = "image.t2i"
        if intent.reference_artifact_id is not None:
            required = "image.i2i"
        if required not in capabilities:
            raise ValueError(f"model does not support {required}")
        if intent.reference_artifact_id is not None:
            constraint = op.reference_constraints.get("reference_image")
            if constraint is None or constraint.max < 1:
                raise ValueError("model does not accept a reference_image")

    async def compile(
        self,
        intent: Any,
        model: Any,
        references: list[Any],
        *,
        invoke_model_value: str,
    ) -> Any:
        self.validate(intent, model)
        resolved = {ref.role: ref for ref in references}
        ref_image = resolved.get("reference_image")
        body, operation, fingerprints = _build_image_body(
            invoke_model_value,
            prompt=intent.prompt,
            size=intent.size or "1024x768",
            canonical_image_bytes=ref_image.content_bytes if ref_image is not None else None,
            canonical_image_mime=ref_image.mime_type if ref_image is not None else "image/png",
        )
        from app.providers.runtime import CompiledImageRequest

        artifact_ids = [str(ref_image.artifact_id)] if ref_image is not None else []
        fps = [ref_image.fingerprint] if ref_image is not None and ref_image.fingerprint else []
        return CompiledImageRequest(
            provider_type="agnes",
            protocol_profile=AGNES_CN_PROFILE,
            model_id=invoke_model_value,
            operation="image.generate",
            wire_request=cast(dict[str, JsonValue], body),
            request_schema_version=model.manifest_version,
            safe_request_summary=cast(
                dict[str, JsonValue],
                _compiled_summary(
                    operation=operation,
                    invoke_model_value=invoke_model_value,
                    reference_artifact_ids=artifact_ids,
                    reference_fingerprints=fps,
                    schema_version=model.manifest_version,
                ),
            ),
            reference_artifact_ids=[ref_image.artifact_id] if ref_image is not None else [],
            reference_fingerprints=fps,
        )


class AgnesVideoCompiler:
    """Validates a video intent against the catalog manifest and compiles the
    wire request (first-frame I2V) using the same body builder as the HubClient."""

    def validate(self, intent: Any, model: Any) -> None:
        op = model.operations.get("video.generate")
        if op is None:
            raise ValueError("model does not support video.generate")
        capabilities = set(op.capabilities)
        if not ("video.i2v" in capabilities or "video.i2v.first_frame" in capabilities):
            raise ValueError("model does not support video.i2v")
        first_refs = [ref for ref in intent.references if ref.role == "first_frame"]
        if not first_refs:
            raise ValueError("video.generate requires a first_frame reference")
        constraint = op.reference_constraints.get("first_frame")
        if constraint is None or constraint.max < 1:
            raise ValueError("model does not accept a first_frame reference")
        if len(first_refs) > constraint.max:
            raise ValueError("too many first_frame references")
        output = intent.output
        if output.aspect_ratio not in {None, "9:16"}:
            raise ValueError("Agnes Video V2.0 catalog revision only supports 9:16")
        if output.generate_audio not in {None, False}:
            raise ValueError("Agnes Video V2.0 compiler cannot request native audio")
        if output.duration_seconds is not None:
            frames = output.duration_seconds * 24 + 1
            _validate_video_shape(num_frames=frames, frame_rate=24)

    async def compile(
        self,
        intent: Any,
        model: Any,
        references: list[Any],
        *,
        invoke_model_value: str,
    ) -> Any:
        self.validate(intent, model)
        first = next(ref for ref in references if ref.role == "first_frame")
        duration_seconds = intent.output.duration_seconds or 5
        num_frames = duration_seconds * 24 + 1
        if first.content_bytes is not None:
            body, operation, _refs, _transport = _build_video_body(
                invoke_model_value,
                prompt=intent.prompt,
                image_bytes=first.content_bytes,
                image_mime=first.mime_type,
                num_frames=num_frames,
                frame_rate=24,
            )
        elif first.content_url is not None:
            body, operation, _refs, _transport = _build_video_body(
                invoke_model_value,
                prompt=intent.prompt,
                image_url=first.content_url,
                num_frames=num_frames,
                frame_rate=24,
            )
        else:
            raise ValueError("video first_frame reference has no bytes or URL")
        from app.providers.runtime import CompiledVideoRequest

        fps = [first.fingerprint] if first.fingerprint else []
        summary = _compiled_summary(
            operation=operation,
            invoke_model_value=invoke_model_value,
            reference_artifact_ids=[str(first.artifact_id)],
            reference_fingerprints=fps,
            schema_version=model.manifest_version,
        )
        summary.update(
            {
                "aspect_ratio": "9:16",
                "duration_seconds": duration_seconds,
                "num_frames": num_frames,
                "frame_rate": 24,
                "native_audio": False,
            }
        )
        return CompiledVideoRequest(
            provider_type="agnes",
            protocol_profile=AGNES_CN_PROFILE,
            model_id=invoke_model_value,
            operation="video.generate",
            wire_request=cast(dict[str, JsonValue], body),
            request_schema_version=model.manifest_version,
            safe_request_summary=cast(dict[str, JsonValue], summary),
            reference_artifact_ids=[first.artifact_id],
            reference_fingerprints=fps,
        )


class AgnesRuntime:
    """Unified runtime. ``submit_*`` sends the compiled wire request verbatim;
    polling uses the sanitized resume token's query kind."""

    provider = "agnes"
    protocol_profile = AGNES_CN_PROFILE

    _VIDEO_REQUEST_TIMEOUT_S = 120.0
    _IMAGE_REQUEST_TIMEOUT_S = 150.0

    def __init__(
        self,
        *,
        connection: Any | None = None,
        settings: Settings | None = None,
        host: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._transport = transport
        self._host = normalize_agnes_host(host or self._settings.agnes_base_url)
        self._key = self._settings.agnes_api_key.strip()
        self._enabled = self._settings.agnes_enabled

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
        }

    def _configured(self) -> bool:
        return bool(self._key and self._enabled)

    async def submit_image(self, request: Any) -> Any:
        from app.providers.runtime import ProviderResumeToken, SubmissionResult

        if not self._configured():
            raise RuntimeError("Agnes China connection is not configured")
        try:
            response = await _post_json(
                self._host,
                AGNES_IMAGE_PATH,
                headers=self._headers(),
                body=request.wire_request,
                timeout=self._IMAGE_REQUEST_TIMEOUT_S,
                transport=self._transport,
            )
        except httpx.TransportError as exc:
            return SubmissionResult(
                status="unknown_submission",
                error_code="PROVIDER_SUBMISSION_UNKNOWN",
                error=type(exc).__name__,
                request_fingerprint=_request_fingerprint(request.wire_request),
                request_summary=request.safe_request_summary,
            )
        data = _json_object(response)
        image_url = _image_result_url(data)
        if response.status_code >= 400 or not image_url:
            return SubmissionResult(
                status="failed",
                error_code=(
                    _error_code(response.status_code)
                    if response.status_code >= 400
                    else "PROVIDER_RESPONSE_INVALID"
                ),
                error=f"Agnes image request failed ({response.status_code})",
                retry_after_seconds=_retry_after_seconds(response),
                request_fingerprint=_request_fingerprint(request.wire_request),
                request_summary=request.safe_request_summary,
            )
        remote_id = f"agnes-image-{uuid4()}"
        token = ProviderResumeToken(
            provider_type="agnes",
            protocol_profile=AGNES_CN_PROFILE,
            remote_task_id=remote_id,
        )
        return SubmissionResult(
            remote_task_id=remote_id,
            status="succeeded",
            artifact_uri=image_url,
            request_fingerprint=_request_fingerprint(request.wire_request),
            request_summary=request.safe_request_summary,
            resume_token=token,
        )

    async def submit_video(self, request: Any) -> Any:
        from app.providers.runtime import ProviderResumeToken, SubmissionResult

        if not self._configured():
            raise RuntimeError("Agnes China connection is not configured")
        try:
            response = await _post_json(
                self._host,
                AGNES_VIDEO_CREATE_PATH,
                headers=self._headers(),
                body=request.wire_request,
                timeout=self._VIDEO_REQUEST_TIMEOUT_S,
                transport=self._transport,
            )
        except httpx.TransportError as exc:
            return SubmissionResult(
                status="unknown_submission",
                error_code="PROVIDER_SUBMISSION_UNKNOWN",
                error=type(exc).__name__,
                request_fingerprint=_request_fingerprint(request.wire_request),
                request_summary=request.safe_request_summary,
            )
        data = _json_object(response)
        video_id = data.get("video_id")
        task_id = data.get("task_id")
        video_id_value = str(video_id) if video_id is not None and str(video_id) else None
        task_id_value = str(task_id) if task_id is not None and str(task_id) else None
        if response.status_code >= 400 or (video_id_value is None and task_id_value is None):
            return SubmissionResult(
                status="failed",
                error_code=(
                    _error_code(response.status_code)
                    if response.status_code >= 400
                    else "PROVIDER_RESPONSE_INVALID"
                ),
                error=f"Agnes video request failed ({response.status_code})",
                retry_after_seconds=_retry_after_seconds(response),
                request_fingerprint=_request_fingerprint(request.wire_request),
                request_summary=request.safe_request_summary,
            )
        remote_id = video_id_value or task_id_value
        assert remote_id is not None
        remote_secondary_id = task_id_value if video_id_value else None
        query_kind: str = "video_id" if video_id_value else "task_id"
        token = ProviderResumeToken(
            provider_type="agnes",
            protocol_profile=AGNES_CN_PROFILE,
            remote_task_id=remote_id,
            remote_secondary_id=remote_secondary_id,
            query_kind=query_kind,
        )
        return SubmissionResult(
            remote_task_id=remote_id,
            remote_secondary_id=remote_secondary_id,
            query_kind=query_kind,
            status=str(data.get("status") or "queued"),
            request_fingerprint=_request_fingerprint(request.wire_request),
            request_summary=request.safe_request_summary,
            resume_token=token,
        )

    async def poll_video(self, resume: Any) -> Any:
        from app.providers.runtime import PollResult

        if not self._configured():
            raise RuntimeError("Agnes China connection is not configured")
        query_kind = resume.query_kind
        if query_kind not in {"video_id", "task_id"}:
            raise ValueError("video poll query kind is required")
        if query_kind == "video_id":
            path = AGNES_VIDEO_BY_ID_PATH
            params = {"video_id": resume.remote_task_id}
        else:
            path = f"{AGNES_VIDEO_CREATE_PATH}/{resume.remote_task_id}"
            params = None
        try:
            response = await _get_json(
                self._host,
                path,
                headers=self._headers(),
                params=params,
                timeout=60.0,
                transport=self._transport,
            )
        except httpx.TransportError:
            return PollResult(
                status="running",
                error_code="PROVIDER_POLL_TRANSIENT",
            )
        data = _json_object(response)
        if response.status_code >= 400:
            if response.status_code == 429 or response.status_code >= 500:
                return PollResult(
                    status="running",
                    http_status=response.status_code,
                    error_code=(
                        "PROVIDER_RATE_LIMITED"
                        if response.status_code == 429
                        else "PROVIDER_POLL_TRANSIENT"
                    ),
                    retry_after_seconds=_retry_after_seconds(response),
                )
            return PollResult(
                status="failed",
                http_status=response.status_code,
                error_code=_error_code(response.status_code),
            )
        raw_status = str(data.get("status") or "unknown").lower()
        if raw_status in {"succeeded", "completed", "success", "done"}:
            status = "succeeded"
        elif raw_status in {"failed", "error", "cancelled"}:
            status = "failed" if raw_status != "cancelled" else "cancelled"
        elif raw_status in {"queued", "pending"}:
            status = "queued"
        else:
            status = "running"
        uri = _video_result_url(data)
        progress_value = data.get("progress", 0)
        try:
            progress = float(progress_value or 0)
        except (TypeError, ValueError):
            progress = 0.0
        if progress > 1:
            progress /= 100.0
        result = PollResult(status=status, progress=progress, artifact_uri=uri)
        if status == "failed":
            result = result.model_copy(update={"error_code": "PROVIDER_TASK_FAILED"})
        return result

    async def cancel_video(self, resume: Any) -> Any:
        from app.providers.runtime import CancelResult

        return CancelResult(status="cancelled")

    async def fetch_cost(self, resume: Any) -> Any:
        from app.providers.runtime import CostResult

        return CostResult(amount=0.0, currency="USD", units=1.0)


def _agnes_runtime_factory(
    *,
    connection: Any | None = None,
    settings: Settings | None = None,
    host: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> AgnesRuntime:
    return AgnesRuntime(
        connection=connection,
        settings=settings,
        host=host,
        transport=transport,
    )


def _agnes_compiler_factory() -> tuple[AgnesImageCompiler, AgnesVideoCompiler]:
    return AgnesImageCompiler(), AgnesVideoCompiler()
