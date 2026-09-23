"""Generic OpenAI-compatible image/video protocol adapter.

The adapter is deliberately keyed by protocol, not by a supplier name.  A
workspace connection only provides a base URL and an encrypted API key; the
model id is discovered from ``GET /v1/models`` and selected by the user.  The
capability manifest is the explicit contract that tells the compiler which
wire shape the selected model uses.

This is intentionally a conservative subset:

* images use ``/v1/images/generations`` and ``/v1/images/edits``;
* videos use an async ``/v1/videos`` resource and ``GET/DELETE
  /v1/videos/{id}``;
* only URL outputs are accepted, because the platform artifact pipeline needs a
  fetchable result rather than an unbounded base64 response.

Other media protocols can reuse the same registry seam without adding another
supplier branch to the connection service.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections.abc import Mapping
from typing import Any, cast
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from pydantic import JsonValue

from app.config import Settings, get_settings
from app.providers.manifest import ModelCapabilityManifest
from app.providers.runtime import (
    CancelResult,
    CompiledImageRequest,
    CompiledVideoRequest,
    CostResult,
    PollResult,
    ProviderResumeToken,
    SubmissionResult,
    validate_compiled_submission,
)

OPENAI_MEDIA_PROVIDER = "openai_compatible_media"
OPENAI_MEDIA_PROFILE = "openai_media_v1"
OPENAI_MEDIA_DEFAULT_HOST = "https://api.openai.com/v1"


def _base_url(host: str) -> str:
    value = host.strip().rstrip("/")
    if not value:
        raise ValueError("OpenAI-compatible media base URL is empty")
    return value if value.endswith("/v1") else f"{value}/v1"


def _json_object(response: httpx.Response) -> dict[str, Any]:
    try:
        value = response.json()
    except (ValueError, json.JSONDecodeError):
        return {}
    return dict(value) if isinstance(value, Mapping) else {}


def _first_url(data: Mapping[str, Any]) -> str | None:
    values = data.get("data")
    candidates: list[Any] = values if isinstance(values, list) else [values]
    candidates.extend(
        [
            data.get("url"),
            data.get("output_url"),
            data.get("video_url"),
            data.get("result_url"),
        ]
    )
    for item in candidates:
        if isinstance(item, str) and item.strip().startswith(("http://", "https://")):
            return item.strip()
        if isinstance(item, Mapping):
            for key in ("url", "output_url", "video_url", "result_url"):
                nested = item.get(key)
                if isinstance(nested, str) and nested.strip().startswith(("http://", "https://")):
                    return nested.strip()
    return None


def _task_id(data: Mapping[str, Any]) -> str | None:
    for key in ("id", "video_id", "task_id"):
        value = data.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _status(value: Any, *, default: str = "running") -> str:
    normalized = str(value or default).strip().lower()
    if normalized in {"succeeded", "completed", "success", "done"}:
        return "succeeded"
    if normalized in {"failed", "error", "rejected", "expired"}:
        return "failed"
    if normalized in {"cancelled", "canceled"}:
        return "cancelled"
    if normalized in {"queued", "pending", "submitted"}:
        return "queued"
    return "running"


def _error_code(status_code: int) -> str:
    if status_code in {401, 403}:
        return "PROVIDER_AUTH_REJECTED"
    if status_code == 404:
        return "PROVIDER_ENDPOINT_NOT_FOUND"
    if status_code == 429:
        return "PROVIDER_RATE_LIMITED"
    if 400 <= status_code < 500:
        return "PROVIDER_REQUEST_REJECTED"
    if status_code >= 500:
        return "PROVIDER_UPSTREAM_FAILURE"
    return "PROVIDER_RESPONSE_INVALID"


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    if value is None:
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


def _fingerprint(payload: Mapping[str, Any]) -> str:
    # The fingerprint is an audit value only.  The compiler's safe summary never
    # contains the base64 media fields, and this digest is not reversible.
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _summary(payload: Mapping[str, Any], *, operation: str) -> dict[str, JsonValue]:
    return cast(
        dict[str, JsonValue],
        {
            "protocol_profile": OPENAI_MEDIA_PROFILE,
            "host": urlsplit(str(payload.get("_host") or "")).hostname or "",
            "operation": operation,
            "model": str(payload.get("model") or ""),
            "reference_count": int(payload.get("reference_count") or 0),
        },
    )


class OpenAICompatibleMediaClient:
    """Low-level probe client for a generic OpenAI-compatible media endpoint."""

    def __init__(
        self,
        settings: Settings | None = None,
        host: str | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        cfg = settings or get_settings()
        self._settings = cfg
        self._key = cfg.openai_compatible_media_api_key.strip()
        self._host = _base_url(host or cfg.openai_compatible_media_base_url)
        self._transport = transport
        self._image_model = cfg.openai_compatible_media_image_model.strip()
        self._video_model = cfg.openai_compatible_media_video_model.strip()

    def configured(self) -> bool:
        return bool(self._key and self._settings.openai_compatible_media_enabled)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._key}"}

    async def create_image(
        self,
        *,
        prompt: str,
        size: str = "1024x1024",
        ratio: str | None = None,
        canonical_image_bytes: bytes | None = None,
        canonical_image_mime: str = "image/png",
        reference_artifact_id: str | None = None,
    ) -> dict[str, Any]:
        if not self.configured():
            raise RuntimeError("OpenAI-compatible media connection is not configured")
        payload: dict[str, Any] = {
            "model": self._image_model,
            "prompt": prompt,
            "size": size,
            "n": 1,
            "response_format": "url",
        }
        if ratio:
            payload["aspect_ratio"] = ratio
        if reference_artifact_id:
            payload["reference_artifact_ids"] = [reference_artifact_id]
        response = await self._post_image(payload, canonical_image_bytes, canonical_image_mime)
        data = _json_object(response)
        image_url = _first_url(data)
        if response.status_code >= 400 or image_url is None:
            return {
                "status": "failed",
                "http_status": response.status_code,
                "error_code": _error_code(response.status_code),
                "retry_after_seconds": _retry_after(response),
            }
        return {
            "status": "succeeded",
            "remote_task_id": f"openai-image-{uuid4()}",
            "artifact_uri": image_url,
            "http_status": response.status_code,
        }

    async def _post_image(
        self,
        payload: dict[str, Any],
        image_bytes: bytes | None,
        image_mime: str,
    ) -> httpx.Response:
        async with httpx.AsyncClient(
            timeout=self._settings.openai_compatible_media_timeout_seconds,
            transport=self._transport,
        ) as client:
            if image_bytes is None:
                return await client.post(
                    f"{self._host}/images/generations",
                    headers={**self._headers(), "Content-Type": "application/json"},
                    json=payload,
                )
            data = {
                key: str(value)
                for key, value in payload.items()
                if key != "reference_artifact_ids"
            }
            return await client.post(
                f"{self._host}/images/edits",
                headers=self._headers(),
                data=data,
                files={"image": ("reference", image_bytes, image_mime)},
            )

    async def create_video(
        self,
        *,
        prompt: str,
        image_bytes: bytes | None = None,
        image_mime: str = "image/png",
        reference_artifact_ids: list[str] | None = None,
        reference_fingerprints: list[str] | None = None,
    ) -> dict[str, Any]:
        if not self.configured():
            raise RuntimeError("OpenAI-compatible media connection is not configured")
        payload: dict[str, Any] = {
            "model": self._video_model,
            "prompt": prompt,
            "seconds": "5",
            "size": "720x1280",
        }
        if image_bytes is not None:
            payload["input_reference"] = "file"
        response = await self._post_video(payload, image_bytes, image_mime)
        data = _json_object(response)
        remote_id = _task_id(data)
        if response.status_code >= 400 or remote_id is None:
            return {
                "status": "failed",
                "http_status": response.status_code,
                "error_code": _error_code(response.status_code),
                "retry_after_seconds": _retry_after(response),
            }
        return {
            "status": _status(data.get("status"), default="queued"),
            "remote_task_id": remote_id,
            "http_status": response.status_code,
            "query_kind": "video_id",
        }

    async def _post_video(
        self,
        payload: dict[str, Any],
        image_bytes: bytes | None,
        image_mime: str,
    ) -> httpx.Response:
        async with httpx.AsyncClient(
            timeout=self._settings.openai_compatible_media_timeout_seconds,
            transport=self._transport,
        ) as client:
            if image_bytes is None:
                return await client.post(
                    f"{self._host}/videos",
                    headers={**self._headers(), "Content-Type": "application/json"},
                    json=payload,
                )
            data = {key: str(value) for key, value in payload.items()}
            return await client.post(
                f"{self._host}/videos",
                headers=self._headers(),
                data=data,
                files={"input_reference": ("first-frame", image_bytes, image_mime)},
            )

    async def poll_video(self, remote_task_id: str, **_: Any) -> dict[str, Any]:
        if not self.configured():
            raise RuntimeError("OpenAI-compatible media connection is not configured")
        async with httpx.AsyncClient(
            timeout=self._settings.openai_compatible_media_timeout_seconds,
            transport=self._transport,
        ) as client:
            response = await client.get(
                f"{self._host}/videos/{remote_task_id}",
                headers=self._headers(),
            )
        data = _json_object(response)
        status = _status(data.get("status"))
        return {
            "status": status if response.status_code < 400 else "failed",
            "progress": float(data.get("progress") or 0),
            "artifact_uri": _first_url(data),
            "http_status": response.status_code,
            "error_code": None if response.status_code < 400 else _error_code(response.status_code),
        }


class OpenAICompatibleImageCompiler:
    def validate(self, intent: Any, model: ModelCapabilityManifest) -> None:
        operation = model.operations.get("image.generate")
        if operation is None:
            raise ValueError("model does not support image.generate")
        required = "image.i2i" if intent.reference_artifact_id is not None else "image.t2i"
        if required not in operation.capabilities:
            raise ValueError(f"model does not support {required}")
        constraint = operation.reference_constraints.get("reference_image")
        if intent.reference_artifact_id is not None and (constraint is None or constraint.max < 1):
            raise ValueError("model does not accept a reference_image")

    async def compile(
        self,
        intent: Any,
        model: ModelCapabilityManifest,
        references: list[Any],
        *,
        invoke_model_value: str,
    ) -> CompiledImageRequest:
        self.validate(intent, model)
        resolved = [ref for ref in references if ref.role == "reference_image"]
        if len(resolved) > 1:
            raise ValueError("OpenAI-compatible image compiler accepts one reference_image")
        ref = resolved[0] if resolved else None
        if intent.reference_artifact_id is not None and (
            ref is None or ref.artifact_id != intent.reference_artifact_id
        ):
            raise ValueError("resolved reference_image does not match the image intent")
        body: dict[str, JsonValue] = {
            "model": invoke_model_value,
            "prompt": intent.prompt,
            "size": intent.size or "1024x1024",
            "n": 1,
            "response_format": "url",
        }
        if intent.aspect_ratio is not None:
            body["aspect_ratio"] = intent.aspect_ratio
        if ref is not None:
            if ref.content_bytes is not None:
                body["image_b64"] = base64.b64encode(ref.content_bytes).decode("ascii")
                body["image_mime"] = ref.mime_type
            elif ref.content_url is not None:
                body["image_url"] = ref.content_url
            else:
                raise ValueError("reference_image has no bytes or URL")
        summary = {
            "operation": "image.generate",
            "model": invoke_model_value,
            "reference_count": 1 if ref is not None else 0,
            "request_schema_version": model.manifest_version,
        }
        return CompiledImageRequest(
            provider_type=OPENAI_MEDIA_PROVIDER,
            protocol_profile=OPENAI_MEDIA_PROFILE,
            model_id=invoke_model_value,
            operation="image.generate",
            wire_request=body,
            request_schema_version=model.manifest_version,
            safe_request_summary=cast(dict[str, JsonValue], summary),
            reference_artifact_ids=[ref.artifact_id] if ref is not None else [],
            reference_fingerprints=[ref.fingerprint] if ref is not None and ref.fingerprint else [],
        )


class OpenAICompatibleVideoCompiler:
    def validate(self, intent: Any, model: ModelCapabilityManifest) -> None:
        operation = model.operations.get("video.generate")
        if operation is None:
            raise ValueError("model does not support video.generate")
        if "video.i2v.first_frame" not in operation.capabilities:
            raise ValueError("model does not support video.i2v.first_frame")
        if intent.output.generate_audio not in {None, False}:
            raise ValueError("OpenAI-compatible video contract does not support native audio")

    async def compile(
        self,
        intent: Any,
        model: ModelCapabilityManifest,
        references: list[Any],
        *,
        invoke_model_value: str,
    ) -> CompiledVideoRequest:
        self.validate(intent, model)
        expected = next((ref for ref in intent.references if ref.role == "first_frame"), None)
        resolved = [ref for ref in references if ref.role == "first_frame"]
        if (
            expected is None
            or len(resolved) != 1
            or resolved[0].artifact_id != expected.artifact_id
        ):
            raise ValueError("video intent first_frame was not resolved exactly once")
        ref = resolved[0]
        body: dict[str, JsonValue] = {
            "model": invoke_model_value,
            "prompt": intent.prompt,
            "seconds": intent.output.duration_seconds or 5,
            "size": intent.output.resolution or "720x1280",
        }
        if intent.output.aspect_ratio is not None:
            body["aspect_ratio"] = intent.output.aspect_ratio
        if ref.content_bytes is not None:
            body["input_image_b64"] = base64.b64encode(ref.content_bytes).decode("ascii")
            body["input_image_mime"] = ref.mime_type
        elif ref.content_url is not None:
            body["input_image_url"] = ref.content_url
        else:
            raise ValueError("first_frame has no bytes or URL")
        summary = {
            "operation": "video.generate",
            "model": invoke_model_value,
            "reference_count": 1,
            "duration_seconds": body["seconds"],
            "request_schema_version": model.manifest_version,
        }
        return CompiledVideoRequest(
            provider_type=OPENAI_MEDIA_PROVIDER,
            protocol_profile=OPENAI_MEDIA_PROFILE,
            model_id=invoke_model_value,
            operation="video.generate",
            wire_request=body,
            request_schema_version=model.manifest_version,
            safe_request_summary=cast(dict[str, JsonValue], summary),
            reference_artifact_ids=[ref.artifact_id],
            reference_fingerprints=[ref.fingerprint] if ref.fingerprint else [],
        )


class OpenAICompatibleMediaRuntime:
    provider = OPENAI_MEDIA_PROVIDER
    protocol_profile = OPENAI_MEDIA_PROFILE

    def __init__(
        self,
        *,
        connection: Any | None = None,
        settings: Settings | None = None,
        host: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client = OpenAICompatibleMediaClient(
            self._settings,
            host=host or getattr(connection, "base_url", None),
            transport=transport,
        )

    def _configured(self) -> None:
        if not self._client.configured():
            raise RuntimeError("OpenAI-compatible media connection is not configured")

    async def submit_image(self, request: CompiledImageRequest) -> SubmissionResult:
        validate_compiled_submission(
            request,
            provider_type=self.provider,
            protocol_profile=self.protocol_profile,
            operation="image.generate",
        )
        self._configured()
        payload = dict(request.wire_request)
        image_b64 = payload.pop("image_b64", None)
        image_mime = str(payload.pop("image_mime", "image/png"))
        if image_b64 is not None:
            try:
                image_bytes = base64.b64decode(str(image_b64), validate=True)
            except (ValueError, binascii.Error) as exc:
                raise ValueError("compiled image reference is not valid base64") from exc
        else:
            image_bytes = None
        try:
            response = await self._client._post_image(payload, image_bytes, image_mime)
        except httpx.TransportError as exc:
            return SubmissionResult(
                status="unknown_submission",
                error_code="PROVIDER_SUBMISSION_UNKNOWN",
                error=type(exc).__name__,
                request_fingerprint=_fingerprint(request.wire_request),
                request_summary=request.safe_request_summary,
            )
        data = _json_object(response)
        url = _first_url(data)
        if response.status_code >= 400 or url is None:
            return SubmissionResult(
                status="failed",
                error_code=_error_code(response.status_code),
                http_status=response.status_code,
                retry_after_seconds=_retry_after(response),
                request_fingerprint=_fingerprint(request.wire_request),
                request_summary=request.safe_request_summary,
            )
        return SubmissionResult(
            status="succeeded",
            remote_task_id=f"openai-image-{uuid4()}",
            artifact_uri=url,
            http_status=response.status_code,
            request_fingerprint=_fingerprint(request.wire_request),
            request_summary=request.safe_request_summary,
        )

    async def submit_video(self, request: CompiledVideoRequest) -> SubmissionResult:
        validate_compiled_submission(
            request,
            provider_type=self.provider,
            protocol_profile=self.protocol_profile,
            operation="video.generate",
        )
        self._configured()
        payload = dict(request.wire_request)
        image_b64 = payload.pop("input_image_b64", None)
        image_mime = str(payload.pop("input_image_mime", "image/png"))
        if image_b64 is not None:
            try:
                image_bytes = base64.b64decode(str(image_b64), validate=True)
            except (ValueError, binascii.Error) as exc:
                raise ValueError("compiled first_frame is not valid base64") from exc
        else:
            image_bytes = None
            image_url = payload.pop("input_image_url", None)
            if image_url is not None:
                payload["input_reference_url"] = image_url
        try:
            response = await self._client._post_video(payload, image_bytes, image_mime)
        except httpx.TransportError as exc:
            return SubmissionResult(
                status="unknown_submission",
                error_code="PROVIDER_SUBMISSION_UNKNOWN",
                error=type(exc).__name__,
                request_fingerprint=_fingerprint(request.wire_request),
                request_summary=request.safe_request_summary,
            )
        data = _json_object(response)
        remote_id = _task_id(data)
        if response.status_code >= 400 or remote_id is None:
            return SubmissionResult(
                status="unknown_submission" if response.status_code == 0 else "failed",
                error_code=_error_code(response.status_code),
                http_status=response.status_code,
                retry_after_seconds=_retry_after(response),
                request_fingerprint=_fingerprint(request.wire_request),
                request_summary=request.safe_request_summary,
            )
        token = ProviderResumeToken(
            provider_type=self.provider,
            protocol_profile=self.protocol_profile,
            remote_task_id=remote_id,
            query_kind="video_id",
        )
        return SubmissionResult(
            status=_status(data.get("status"), default="queued"),
            remote_task_id=remote_id,
            query_kind="video_id",
            resume_token=token,
            http_status=response.status_code,
            request_fingerprint=_fingerprint(request.wire_request),
            request_summary=request.safe_request_summary,
        )

    async def poll_video(self, resume: ProviderResumeToken) -> PollResult:
        self._configured()
        result = await self._client.poll_video(resume.remote_task_id, query_kind=resume.query_kind)
        return PollResult(
            status=str(result["status"]),
            progress=float(result.get("progress") or 0),
            artifact_uri=result.get("artifact_uri"),
            error_code=result.get("error_code"),
            http_status=result.get("http_status"),
        )

    async def cancel_video(self, resume: ProviderResumeToken) -> CancelResult:
        self._configured()
        async with httpx.AsyncClient(
            timeout=self._settings.openai_compatible_media_timeout_seconds,
        ) as client:
            response = await client.delete(
                f"{self._client._host}/videos/{resume.remote_task_id}",
                headers=self._client._headers(),
            )
        return CancelResult(status="cancelled" if response.status_code < 400 else "failed")

    async def fetch_cost(self, resume: ProviderResumeToken) -> CostResult:
        _ = resume
        return CostResult(amount=None, currency="USD", cost_status="not_reported")


def _openai_compatible_media_runtime_factory(
    *,
    connection: Any | None = None,
    settings: Settings | None = None,
    host: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> OpenAICompatibleMediaRuntime:
    return OpenAICompatibleMediaRuntime(
        connection=connection,
        settings=settings,
        host=host,
        transport=transport,
    )


def _openai_compatible_media_compiler_factory() -> tuple[
    OpenAICompatibleImageCompiler, OpenAICompatibleVideoCompiler
]:
    return OpenAICompatibleImageCompiler(), OpenAICompatibleVideoCompiler()
