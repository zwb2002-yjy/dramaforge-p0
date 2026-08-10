"""Volcengine Ark ``ark_cn_v1`` image and video protocol profile.

Wire contract verified against official Volcengine Ark docs and arkcli
``+gen --dry-run`` (2026-08-07):

- Image (Seedream, synchronous): ``POST {base}/images/generations``
  ``{model, prompt, size, seed, watermark, response_format, image?: [url]}``.
  The image reference array is a TOP-LEVEL ``image`` field; a T2I request omits
  it. Response ``{"data": [{"url": ...}]}`` is a short-lived TOS presigned URL
  and must be downloaded immediately.
- Video (Seedance, asynchronous task): ``POST {base}/contents/generations/tasks``
  ``{model, content: [{type:text,...}, {type:image_url, image_url:{url},
  role:"first_frame"}]}``. Response ``{"id": "cgt-..."}``. Poll
  ``GET {base}/contents/generations/tasks/{id}`` -> ``{id, status,
  content:{video_url}}``; cancel ``DELETE {base}/contents/generations/tasks/{id}``.

Auth is ``Authorization: Bearer <ARK_API_KEY>``. Paid create requests are
single-attempt: transport ambiguity returns ``unknown_submission`` so a caller
cannot accidentally hide a duplicate POST inside the adapter.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from app.config import Settings, get_settings

ARK_CN_PROFILE = "ark_cn_v1"
ARK_CN_HOST = "https://ark.cn-beijing.volces.com/api/v3"
ARK_IMAGE_PATH = "/images/generations"
ARK_VIDEO_CREATE_PATH = "/contents/generations/tasks"


def _require_prompt(prompt: str) -> str:
    value = prompt.strip()
    if not value:
        raise ValueError("prompt must be non-empty")
    return value


def _require_https_reference(value: str) -> str:
    reference = value.strip()
    parsed = urlsplit(reference)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Ark reference must be a public HTTPS URL")
    return reference


def _require_size(size: str) -> str:
    value = size.strip()
    if not value:
        raise ValueError("size must be non-empty")
    return value


def _schema_fingerprint(body: dict[str, object]) -> str:
    """Fingerprint field shape while replacing prompts, references, and tokens."""

    def redacted(value: object, key: str = "") -> object:
        if key == "prompt":
            return "<prompt>"
        if key in {"image", "url", "video_url", "text"}:
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


def _json_object(response: httpx.Response) -> dict[str, Any]:
    try:
        value = response.json()
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _retry_after_seconds(response: httpx.Response) -> float | None:
    retry_after = response.headers.get("Retry-After", "").strip()
    if not retry_after:
        return None
    try:
        return max(float(retry_after), 0.0)
    except ValueError:
        return None


def _image_result_url(data: dict[str, Any]) -> str | None:
    items = data.get("data")
    if not isinstance(items, list) or not items or not isinstance(items[0], dict):
        return None
    value = items[0].get("url")
    return str(value) if isinstance(value, str) and value else None


def _video_result_url(data: dict[str, Any]) -> str | None:
    content = data.get("content")
    if isinstance(content, dict):
        value = content.get("video_url")
        if isinstance(value, str) and value:
            return value
    value = data.get("video_url")
    return str(value) if isinstance(value, str) and value else None


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
    timeout: float,
    transport: httpx.AsyncBaseTransport | None,
) -> httpx.Response:
    async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
        return await client.get(f"{host}{path}", headers=headers)


def _build_image_body(
    model: str,
    *,
    prompt: str,
    size: str,
    reference_url: str | None = None,
    seed: int | None = None,
) -> tuple[dict[str, object], str, list[str]]:
    prompt_value = _require_prompt(prompt)
    size_value = _require_size(size)
    body: dict[str, object] = {
        "model": model,
        "prompt": prompt_value,
        "size": size_value,
        "response_format": "url",
        "watermark": False,
    }
    if seed is not None:
        body["seed"] = seed
    references: list[str] = []
    operation = "image.t2i"
    if reference_url is not None:
        references = [_require_https_reference(reference_url)]
        body["image"] = references
        operation = "image.i2i"
    return body, operation, references


def _build_video_body(
    model: str,
    *,
    prompt: str,
    image_url: str | None,
) -> tuple[dict[str, object], str, list[str]]:
    prompt_value = _require_prompt(prompt)
    content: list[dict[str, object]] = [{"type": "text", "text": prompt_value}]
    references: list[str] = []
    if image_url is not None:
        reference = _require_https_reference(image_url)
        references = [reference]
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": reference},
                "role": "first_frame",
            }
        )
    else:
        raise ValueError("Ark video I2V requires one first-frame reference")
    body: dict[str, object] = {
        "model": model,
        "content": content,
    }
    return body, "video.i2v", references


def _request_fingerprint(body: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


class ArkHubClient:
    """Single-attempt Volcengine Ark protocol client."""

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
        self._host = (host or self._settings.volcengine_base_url).strip().rstrip("/")
        self._key = self._settings.volcengine_api_key.strip()
        self._image_model = self._settings.volcengine_image_model
        self._video_model = self._settings.volcengine_video_model
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
        return bool(self._key and self._settings.volcengine_enabled)

    async def create_image(
        self,
        *,
        prompt: str,
        size: str = "2048x2048",
        reference_url: str | None = None,
        reference_artifact_id: str | None = None,
        reference_fingerprint: str | None = None,
        seed: int | None = None,
    ) -> dict[str, Any]:
        if not self.configured():
            raise RuntimeError("Volcengine Ark connection is not configured")
        body, operation, references = _build_image_body(
            self._image_model,
            prompt=prompt,
            size=size,
            reference_url=reference_url,
            seed=seed,
        )
        request_fingerprint = _request_fingerprint(body)
        summary: dict[str, object] = {
            "protocol_profile": ARK_CN_PROFILE,
            "host": urlsplit(self._host).hostname or "",
            "operation": operation,
            "model": self._image_model,
            "size": str(body.get("size", "")),
            "reference_count": len(references),
            "reference_artifact_ids": ([reference_artifact_id] if reference_artifact_id else []),
            "reference_fingerprints": (
                [reference_fingerprint] if reference_fingerprint else []
            ),
            "reference_transport": "signed_url" if references else "none",
            "request_schema_fingerprint": _schema_fingerprint(body),
        }
        try:
            response = await _post_json(
                self._host,
                ARK_IMAGE_PATH,
                headers=self._headers(),
                body=body,
                timeout=self._IMAGE_REQUEST_TIMEOUT_S,
                transport=self._transport,
            )
        except httpx.TransportError as exc:
            return {
                "status": "unknown_submission",
                "error_code": "PROVIDER_SUBMISSION_UNKNOWN",
                "actual_provider": "volcengine",
                "actual_model": self._image_model,
                "protocol_profile": ARK_CN_PROFILE,
                "request_fingerprint": request_fingerprint,
                "request_summary": summary,
                "reference_fingerprints": list(references),
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
                "error": f"Ark image request failed ({response.status_code})",
                "actual_provider": "volcengine",
                "actual_model": self._image_model,
                "protocol_profile": ARK_CN_PROFILE,
                "request_fingerprint": request_fingerprint,
                "request_summary": summary,
                "reference_fingerprints": list(references),
            }
        remote_id = f"ark-image-{uuid4()}"
        self._tasks[remote_id] = {
            "kind": "image",
            "status": "succeeded",
            "artifact_uri": image_url,
        }
        return {
            "remote_task_id": remote_id,
            "status": "succeeded",
            "artifact_uri": image_url,
            "actual_provider": "volcengine",
            "actual_model": self._image_model,
            "protocol_profile": ARK_CN_PROFILE,
            "request_fingerprint": request_fingerprint,
            "request_summary": summary,
            "reference_fingerprints": list(references),
        }

    async def create_video(
        self,
        *,
        prompt: str,
        image_url: str | None = None,
        reference_artifact_ids: list[str] | None = None,
        reference_fingerprints: list[str] | None = None,
    ) -> dict[str, Any]:
        if not self.configured():
            raise RuntimeError("Volcengine Ark connection is not configured")
        body, operation, references = _build_video_body(
            self._video_model,
            prompt=prompt,
            image_url=image_url,
        )
        request_fingerprint = _request_fingerprint(body)
        summary: dict[str, object] = {
            "protocol_profile": ARK_CN_PROFILE,
            "host": urlsplit(self._host).hostname or "",
            "operation": operation,
            "model": self._video_model,
            "reference_count": len(references),
            "reference_artifact_ids": list(reference_artifact_ids or []),
            "reference_fingerprints": list(reference_fingerprints or []),
            "reference_transport": "signed_url" if references else "none",
            "request_schema_fingerprint": _schema_fingerprint(body),
        }
        try:
            response = await _post_json(
                self._host,
                ARK_VIDEO_CREATE_PATH,
                headers=self._headers(),
                body=body,
                timeout=self._VIDEO_REQUEST_TIMEOUT_S,
                transport=self._transport,
            )
        except httpx.TransportError as exc:
            return {
                "status": "unknown_submission",
                "error_code": "PROVIDER_SUBMISSION_UNKNOWN",
                "actual_provider": "volcengine",
                "actual_model": self._video_model,
                "protocol_profile": ARK_CN_PROFILE,
                "request_fingerprint": request_fingerprint,
                "request_summary": summary,
                "transport_error": type(exc).__name__,
            }
        data = _json_object(response)
        task_id = data.get("id")
        task_id_value = str(task_id) if task_id is not None and str(task_id) else None
        if response.status_code >= 400 or task_id_value is None:
            code = (
                _error_code(response.status_code)
                if response.status_code >= 400
                else "PROVIDER_RESPONSE_INVALID"
            )
            return {
                "status": "failed",
                "http_status": response.status_code,
                "error_code": code,
                "error": f"Ark video request failed ({response.status_code})",
                "actual_provider": "volcengine",
                "actual_model": self._video_model,
                "protocol_profile": ARK_CN_PROFILE,
                "request_fingerprint": request_fingerprint,
                "request_summary": summary,
            }
        assert task_id_value is not None
        self._tasks[task_id_value] = {
            "kind": "video",
            "status": "queued",
        }
        return {
            "remote_task_id": task_id_value,
            "status": "queued",
            "actual_provider": "volcengine",
            "actual_model": self._video_model,
            "protocol_profile": ARK_CN_PROFILE,
            "request_fingerprint": request_fingerprint,
            "request_summary": summary,
        }

    async def poll_video(
        self,
        remote_task_id: str,
        *,
        query_kind: str | None = None,
    ) -> dict[str, Any]:
        if not self.configured():
            raise RuntimeError("Volcengine Ark connection is not configured")
        _ = query_kind  # Ark polls by task id only
        try:
            response = await _get_json(
                self._host,
                f"{ARK_VIDEO_CREATE_PATH}/{remote_task_id}",
                headers=self._headers(),
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
                }
            return {
                "status": "failed",
                "http_status": response.status_code,
                "error_code": _error_code(response.status_code),
                "error": f"Ark video poll failed ({response.status_code})",
            }
        raw_status = str(data.get("status") or "unknown").lower()
        if raw_status in {"succeeded", "completed", "success", "done"}:
            status = "succeeded"
        elif raw_status in {"failed", "error", "expired"}:
            status = "failed"
        elif raw_status in {"queued", "pending"}:
            status = "queued"
        else:
            status = "running"
        uri = _video_result_url(data)
        result: dict[str, Any] = {"status": status}
        if uri:
            result["artifact_uri"] = uri
        if status == "failed":
            result["error_code"] = "PROVIDER_TASK_FAILED"
            result["error"] = "Ark video task failed"
        self._tasks[remote_task_id] = {
            **self._tasks.get(remote_task_id, {}),
            "kind": "video",
            "status": status,
        }
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

    async def cancel(self, remote_task_id: str) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                timeout=30.0,
                transport=self._transport,
            ) as client:
                response = await client.delete(
                    f"{self._host}{ARK_VIDEO_CREATE_PATH}/{remote_task_id}",
                    headers=self._headers(),
                )
            if response.status_code < 400 and remote_task_id in self._tasks:
                self._tasks[remote_task_id]["status"] = "cancelled"
        except httpx.TransportError:
            pass
        return {"status": "cancelled"}

    async def fetch_cost(self, remote_task_id: str) -> dict[str, Any]:
        _ = remote_task_id
        return {"amount": 0.0, "currency": "USD", "units": 1.0}


class ArkImageAdapter:
    provider = "volcengine"
    protocol_profile = ARK_CN_PROFILE

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        host: str | None = None,
    ) -> None:
        self._client = ArkHubClient(settings, transport=transport, host=host)
        self.model = self._client._image_model

    async def create(self, request: dict[str, Any]) -> dict[str, Any]:
        return await self._client.create_image(
            prompt=str(request.get("prompt") or ""),
            size=str(request.get("size") or "2048x2048"),
            reference_url=(str(request["reference_url"]) if request.get("reference_url") else None),
            reference_artifact_id=(
                str(request["reference_artifact_id"])
                if request.get("reference_artifact_id")
                else None
            ),
            reference_fingerprint=(
                str(request["reference_fingerprint"])
                if request.get("reference_fingerprint")
                else None
            ),
            seed=int(request["seed"]) if request.get("seed") is not None else None,
        )

    async def poll(self, remote_task_id: str) -> dict[str, Any]:
        return await self._client.poll(remote_task_id)

    async def cancel(self, remote_task_id: str) -> dict[str, Any]:
        return await self._client.cancel(remote_task_id)

    async def fetch_cost(self, remote_task_id: str) -> dict[str, Any]:
        return await self._client.fetch_cost(remote_task_id)


class ArkVideoAdapter:
    provider = "volcengine"
    protocol_profile = ARK_CN_PROFILE

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        host: str | None = None,
    ) -> None:
        self._client = ArkHubClient(settings, transport=transport, host=host)
        self.model = self._client._video_model

    async def create(self, request: dict[str, Any]) -> dict[str, Any]:
        return await self._client.create_video(
            prompt=str(request.get("prompt") or ""),
            image_url=(str(request["image_url"]) if request.get("image_url") else None),
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
        _ = query_kind  # Ark polls by task id only
        return await self._client.poll_video(remote_task_id)

    async def cancel(self, remote_task_id: str) -> dict[str, Any]:
        return await self._client.cancel(remote_task_id)

    async def fetch_cost(self, remote_task_id: str) -> dict[str, Any]:
        return await self._client.fetch_cost(remote_task_id)


# ---------------------------------------------------------------------------
# Stage B3: unified Ark Compiler + Runtime (single wire owner).
# Only fields already backed by Contract Test / Probe / quality evidence are
# enabled (Seedream image + Seedance content[first_frame]); no invented
# duration/ratio/audio options.
# ---------------------------------------------------------------------------


def _ark_summary(
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


class ArkImageCompiler:
    """Validates an image intent against the Ark catalog manifest and compiles
    the wire request (Seedream) using the same builder as :class:`ArkHubClient`."""

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
        if ref_image is not None and ref_image.content_url is None:
            # A declared reference must travel as an HTTPS URL for Ark; a missing
            # transport must fail closed instead of silently degrading to T2I.
            raise ValueError("Ark reference_image must be an HTTPS URL")
        body, operation, _refs = _build_image_body(
            invoke_model_value,
            prompt=intent.prompt,
            size=intent.size or "2048x2048",
            reference_url=ref_image.content_url if ref_image is not None else None,
            seed=intent.seed,
        )
        from typing import cast as _cast

        from pydantic import JsonValue

        from app.providers.runtime import CompiledImageRequest

        artifact_ids = [str(ref_image.artifact_id)] if ref_image is not None else []
        fps = [ref_image.fingerprint] if ref_image is not None and ref_image.fingerprint else []
        return CompiledImageRequest(
            provider_type="volcengine",
            protocol_profile=ARK_CN_PROFILE,
            model_id=invoke_model_value,
            operation="image.generate",
            wire_request=_cast(dict[str, JsonValue], body),
            request_schema_version=model.manifest_version,
            safe_request_summary=_cast(
                dict[str, JsonValue],
                _ark_summary(
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


class ArkVideoCompiler:
    """Validates a video intent against the Ark catalog manifest and compiles
    the Seedance ``content[]`` first-frame request. No duration/ratio/audio."""

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
        if first.content_url is None:
            raise ValueError("Ark video first_frame must be an HTTPS reference URL")
        body, operation, _refs = _build_video_body(
            invoke_model_value,
            prompt=intent.prompt,
            image_url=first.content_url,
        )
        from typing import cast as _cast

        from pydantic import JsonValue

        from app.providers.runtime import CompiledVideoRequest

        fps = [first.fingerprint] if first.fingerprint else []
        return CompiledVideoRequest(
            provider_type="volcengine",
            protocol_profile=ARK_CN_PROFILE,
            model_id=invoke_model_value,
            operation="video.generate",
            wire_request=_cast(dict[str, JsonValue], body),
            request_schema_version=model.manifest_version,
            safe_request_summary=_cast(
                dict[str, JsonValue],
                _ark_summary(
                    operation=operation,
                    invoke_model_value=invoke_model_value,
                    reference_artifact_ids=[str(first.artifact_id)],
                    reference_fingerprints=fps,
                    schema_version=model.manifest_version,
                ),
            ),
            reference_artifact_ids=[first.artifact_id],
            reference_fingerprints=fps,
        )


class ArkRuntime:
    """Unified Ark runtime. Sends the compiled wire request verbatim; polls by
    task id via the persisted resume token."""

    provider = "volcengine"
    protocol_profile = ARK_CN_PROFILE

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
        self._host = (host or self._settings.volcengine_base_url).strip().rstrip("/")
        self._key = self._settings.volcengine_api_key.strip()
        self._enabled = self._settings.volcengine_enabled

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
            raise RuntimeError("Volcengine Ark connection is not configured")
        try:
            response = await _post_json(
                self._host,
                ARK_IMAGE_PATH,
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
                error=f"Ark image request failed ({response.status_code})",
                retry_after_seconds=_retry_after_seconds(response),
                request_fingerprint=_request_fingerprint(request.wire_request),
                request_summary=request.safe_request_summary,
            )
        remote_id = f"ark-image-{uuid4()}"
        token = ProviderResumeToken(
            provider_type="volcengine",
            protocol_profile=ARK_CN_PROFILE,
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
            raise RuntimeError("Volcengine Ark connection is not configured")
        try:
            response = await _post_json(
                self._host,
                ARK_VIDEO_CREATE_PATH,
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
        task_id = data.get("id")
        task_id_value = str(task_id) if task_id is not None and str(task_id) else None
        if response.status_code >= 400 or task_id_value is None:
            return SubmissionResult(
                status="failed",
                error_code=(
                    _error_code(response.status_code)
                    if response.status_code >= 400
                    else "PROVIDER_RESPONSE_INVALID"
                ),
                error=f"Ark video request failed ({response.status_code})",
                retry_after_seconds=_retry_after_seconds(response),
                request_fingerprint=_request_fingerprint(request.wire_request),
                request_summary=request.safe_request_summary,
            )
        assert task_id_value is not None
        token = ProviderResumeToken(
            provider_type="volcengine",
            protocol_profile=ARK_CN_PROFILE,
            remote_task_id=task_id_value,
        )
        return SubmissionResult(
            remote_task_id=task_id_value,
            status="queued",
            request_fingerprint=_request_fingerprint(request.wire_request),
            request_summary=request.safe_request_summary,
            resume_token=token,
        )

    async def poll_video(self, resume: Any) -> Any:
        from app.providers.runtime import PollResult

        if not self._configured():
            raise RuntimeError("Volcengine Ark connection is not configured")
        try:
            response = await _get_json(
                self._host,
                f"{ARK_VIDEO_CREATE_PATH}/{resume.remote_task_id}",
                headers=self._headers(),
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
                )
            return PollResult(
                status="failed",
                http_status=response.status_code,
                error_code=_error_code(response.status_code),
            )
        raw_status = str(data.get("status") or "unknown").lower()
        if raw_status in {"succeeded", "completed", "success", "done"}:
            status = "succeeded"
        elif raw_status in {"failed", "error", "expired"}:
            status = "failed"
        elif raw_status in {"queued", "pending"}:
            status = "queued"
        else:
            status = "running"
        uri = _video_result_url(data)
        result = PollResult(status=status, artifact_uri=uri)
        if status == "failed":
            result = result.model_copy(update={"error_code": "PROVIDER_TASK_FAILED"})
        return result

    async def cancel_video(self, resume: Any) -> Any:
        from app.providers.runtime import CancelResult

        try:
            async with httpx.AsyncClient(
                timeout=30.0, transport=self._transport
            ) as client:
                await client.delete(
                    f"{self._host}{ARK_VIDEO_CREATE_PATH}/{resume.remote_task_id}",
                    headers=self._headers(),
                )
        except httpx.TransportError:
            pass
        return CancelResult(status="cancelled")

    async def fetch_cost(self, resume: Any) -> Any:
        from app.providers.runtime import CostResult

        return CostResult(amount=0.0, currency="USD", units=1.0)


def _ark_runtime_factory(
    *,
    connection: Any | None = None,
    settings: Settings | None = None,
    host: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ArkRuntime:
    return ArkRuntime(
        connection=connection,
        settings=settings,
        host=host,
        transport=transport,
    )


def _ark_compiler_factory() -> tuple[ArkImageCompiler, ArkVideoCompiler]:
    return ArkImageCompiler(), ArkVideoCompiler()
