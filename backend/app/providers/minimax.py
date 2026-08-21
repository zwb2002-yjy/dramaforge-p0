"""MiniMax ``minimax_cn_v1`` image and H3 video protocol profile.

Wire contracts are frozen from MiniMax's official API docs on 2026-08-13:

- Image I2I: ``POST https://api.minimaxi.com/v1/image_generation`` with
  ``subject_reference:[{type:"character", image_file:<https-url>}]``; the
  synchronous response is ``data.image_urls[0]``.
- H3 I2V: ``POST /v2/video_generation`` with a text item and one
  ``image_url`` role ``first_frame``; poll ``GET
  /v2/query/video_generation/{task_id}`` and read ``task.content.url``.
  Queued tasks may be cancelled with ``DELETE /v2/video_generation/{task_id}``.

Only the documented first-launch subset is exposed: exactly one image
reference and exactly one video first frame. Create calls are single-attempt;
ambiguous transport failures fail closed as ``unknown_submission``.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, cast
from urllib.parse import urlsplit

import httpx
from pydantic import JsonValue

from app.config import Settings, get_settings

MINIMAX_CN_PROFILE = "minimax_cn_v1"
MINIMAX_CN_HOST = "https://api.minimaxi.com"
MINIMAX_IMAGE_PATH = "/v1/image_generation"
MINIMAX_VIDEO_CREATE_PATH = "/v2/video_generation"
MINIMAX_VIDEO_QUERY_PATH = "/v2/query/video_generation/{task_id}"
MINIMAX_VIDEO_CANCEL_PATH = "/v2/video_generation/{task_id}"


def _require_prompt(prompt: str) -> str:
    value = prompt.strip()
    if not value:
        raise ValueError("prompt must be non-empty")
    return value


def _require_https_reference(value: str) -> str:
    reference = value.strip()
    parsed = urlsplit(reference)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("MiniMax reference must be a public HTTPS URL")
    return reference


def _request_fingerprint(body: dict[str, object]) -> str:
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _json_object(response: httpx.Response) -> dict[str, Any]:
    try:
        value = response.json()
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _error_code(status_code: int) -> str:
    if status_code == 400:
        return "PROVIDER_BAD_REQUEST"
    if status_code == 401:
        return "PROVIDER_AUTH_FAILED"
    if status_code in {402, 403}:
        return "PROVIDER_FORBIDDEN"
    if status_code == 429:
        return "PROVIDER_RATE_LIMITED"
    if status_code >= 500:
        return "PROVIDER_UNAVAILABLE"
    return "PROVIDER_REQUEST_FAILED"


def _retry_after_seconds(response: httpx.Response) -> float | None:
    raw = response.headers.get("Retry-After", "").strip()
    if not raw:
        return None
    try:
        return max(float(raw), 0.0)
    except ValueError:
        return None


def _api_succeeded(data: dict[str, Any]) -> bool:
    base_resp = data.get("base_resp")
    return not isinstance(base_resp, dict) or base_resp.get("status_code") in {None, 0}


def _image_result_url(data: dict[str, Any]) -> str | None:
    nested = data.get("data")
    if not isinstance(nested, dict):
        return None
    urls = nested.get("image_urls")
    if not isinstance(urls, list) or not urls:
        return None
    value = urls[0]
    return value if isinstance(value, str) and value else None


def _video_task(data: dict[str, Any]) -> dict[str, Any]:
    task = data.get("task")
    return task if isinstance(task, dict) else {}


def _video_result_url(data: dict[str, Any]) -> str | None:
    content = _video_task(data).get("content")
    if not isinstance(content, dict):
        return None
    value = content.get("url")
    return value if isinstance(value, str) and value else None


def _build_image_body(
    model: str,
    *,
    prompt: str,
    reference_url: str,
) -> tuple[dict[str, object], list[str]]:
    reference = _require_https_reference(reference_url)
    body: dict[str, object] = {
        "model": model,
        "prompt": _require_prompt(prompt),
        "aspect_ratio": "1:1",
        "response_format": "url",
        "n": 1,
        "prompt_optimizer": False,
        "aigc_watermark": False,
        "subject_reference": [{"type": "character", "image_file": reference}],
    }
    return body, [reference]


def _build_video_body(
    model: str,
    *,
    prompt: str,
    first_frame_url: str,
) -> tuple[dict[str, object], list[str]]:
    reference = _require_https_reference(first_frame_url)
    body: dict[str, object] = {
        "model": model,
        "content": [
            {"type": "text", "text": _require_prompt(prompt)},
            {"type": "image_url", "image_url": {"url": reference}, "role": "first_frame"},
        ],
        "resolution": "768P",
        "duration": 5,
        "ratio": "adaptive",
        "aigc_watermark": False,
    }
    return body, [reference]


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


def _summary(
    *,
    operation: str,
    model: str,
    artifact_ids: list[str],
    fingerprints: list[str],
    schema_version: str,
) -> dict[str, object]:
    return {
        "operation": operation,
        "model": model,
        "reference_artifact_ids": artifact_ids,
        "reference_fingerprints": fingerprints,
        "request_schema_version": schema_version,
    }


class MiniMaxHubClient:
    """Single-attempt MiniMax protocol client used by probes and compatibility adapters."""

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
        self._host = (host or self._settings.minimax_base_url).strip().rstrip("/")
        self._key = self._settings.minimax_api_key.strip()
        self._image_model = self._settings.minimax_image_model
        self._video_model = self._settings.minimax_video_model

    @property
    def host(self) -> str:
        return self._host

    def configured(self) -> bool:
        return bool(self._settings.minimax_enabled and self._key)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"}

    async def create_image(
        self,
        *,
        prompt: str,
        reference_url: str,
        reference_artifact_id: str | None = None,
        reference_fingerprint: str | None = None,
    ) -> dict[str, Any]:
        if not self.configured():
            raise RuntimeError("MiniMax connection is not configured")
        body, references = _build_image_body(
            self._image_model, prompt=prompt, reference_url=reference_url
        )
        request_fingerprint = _request_fingerprint(body)
        summary = _summary(
            operation="image.i2i.character",
            model=self._image_model,
            artifact_ids=[reference_artifact_id] if reference_artifact_id else [],
            fingerprints=[reference_fingerprint] if reference_fingerprint else [],
            schema_version="2026-08-13",
        )
        try:
            response = await _post_json(
                self._host,
                MINIMAX_IMAGE_PATH,
                headers=self._headers(),
                body=body,
                timeout=self._IMAGE_REQUEST_TIMEOUT_S,
                transport=self._transport,
            )
        except httpx.TransportError as exc:
            return {
                "status": "unknown_submission",
                "error_code": "PROVIDER_SUBMISSION_UNKNOWN",
                "actual_provider": "minimax",
                "actual_model": self._image_model,
                "protocol_profile": MINIMAX_CN_PROFILE,
                "request_fingerprint": request_fingerprint,
                "request_summary": summary,
                "reference_fingerprints": references,
                "transport_error": type(exc).__name__,
            }
        data = _json_object(response)
        uri = _image_result_url(data)
        if response.status_code >= 400 or not _api_succeeded(data) or uri is None:
            return {
                "status": "failed",
                "http_status": response.status_code,
                "error_code": _error_code(response.status_code)
                if response.status_code >= 400
                else "PROVIDER_RESPONSE_INVALID",
                "actual_provider": "minimax",
                "actual_model": self._image_model,
                "protocol_profile": MINIMAX_CN_PROFILE,
                "request_fingerprint": request_fingerprint,
                "request_summary": summary,
                "reference_fingerprints": references,
            }
        return {
            "remote_task_id": str(data.get("id") or "minimax-image"),
            "status": "succeeded",
            "artifact_uri": uri,
            "actual_provider": "minimax",
            "actual_model": self._image_model,
            "protocol_profile": MINIMAX_CN_PROFILE,
            "request_fingerprint": request_fingerprint,
            "request_summary": summary,
            "reference_fingerprints": references,
        }

    async def create_video(
        self,
        *,
        prompt: str,
        image_url: str,
        reference_artifact_ids: list[str] | None = None,
        reference_fingerprints: list[str] | None = None,
    ) -> dict[str, Any]:
        if not self.configured():
            raise RuntimeError("MiniMax connection is not configured")
        body, references = _build_video_body(
            self._video_model, prompt=prompt, first_frame_url=image_url
        )
        request_fingerprint = _request_fingerprint(body)
        summary = _summary(
            operation="video.i2v.first_frame",
            model=self._video_model,
            artifact_ids=list(reference_artifact_ids or []),
            fingerprints=list(reference_fingerprints or []),
            schema_version="2026-08-13",
        )
        try:
            response = await _post_json(
                self._host,
                MINIMAX_VIDEO_CREATE_PATH,
                headers=self._headers(),
                body=body,
                timeout=self._VIDEO_REQUEST_TIMEOUT_S,
                transport=self._transport,
            )
        except httpx.TransportError as exc:
            return {
                "status": "unknown_submission",
                "error_code": "PROVIDER_SUBMISSION_UNKNOWN",
                "actual_provider": "minimax",
                "actual_model": self._video_model,
                "protocol_profile": MINIMAX_CN_PROFILE,
                "request_fingerprint": request_fingerprint,
                "request_summary": summary,
                "transport_error": type(exc).__name__,
            }
        data = _json_object(response)
        task_id = data.get("task_id")
        if response.status_code >= 400 or not _api_succeeded(data) or not task_id:
            return {
                "status": "failed",
                "http_status": response.status_code,
                "error_code": _error_code(response.status_code)
                if response.status_code >= 400
                else "PROVIDER_RESPONSE_INVALID",
                "actual_provider": "minimax",
                "actual_model": self._video_model,
                "protocol_profile": MINIMAX_CN_PROFILE,
                "request_fingerprint": request_fingerprint,
                "request_summary": summary,
            }
        return {
            "remote_task_id": str(task_id),
            "status": "queued",
            "actual_provider": "minimax",
            "actual_model": self._video_model,
            "protocol_profile": MINIMAX_CN_PROFILE,
            "request_fingerprint": request_fingerprint,
            "request_summary": summary,
        }

    async def poll_video(
        self, remote_task_id: str, *, query_kind: str | None = None
    ) -> dict[str, Any]:
        _ = query_kind
        if not self.configured():
            raise RuntimeError("MiniMax connection is not configured")
        try:
            response = await _get_json(
                self._host,
                MINIMAX_VIDEO_QUERY_PATH.format(task_id=remote_task_id),
                headers=self._headers(),
                timeout=60.0,
                transport=self._transport,
            )
        except httpx.TransportError as exc:
            return {
                "status": "running",
                "error_code": "PROVIDER_POLL_TRANSIENT",
                "poll_error": type(exc).__name__,
            }
        data = _json_object(response)
        if response.status_code >= 400 or not _api_succeeded(data):
            if response.status_code == 429 or response.status_code >= 500:
                return {
                    "status": "running",
                    "http_status": response.status_code,
                    "error_code": "PROVIDER_RATE_LIMITED"
                    if response.status_code == 429
                    else "PROVIDER_POLL_TRANSIENT",
                }
            return {
                "status": "failed",
                "http_status": response.status_code,
                "error_code": _error_code(response.status_code),
            }
        raw = str(_video_task(data).get("status") or "").lower()
        status = {
            "queued": "queued",
            "running": "running",
            "succeeded": "succeeded",
            "failed": "failed",
            "cancelled": "cancelled",
        }.get(raw, "running")
        result: dict[str, Any] = {"status": status, "artifact_uri": _video_result_url(data)}
        if status == "failed":
            result["error_code"] = "PROVIDER_TASK_FAILED"
        return result

    async def cancel(self, remote_task_id: str) -> dict[str, Any]:
        if not self.configured():
            raise RuntimeError("MiniMax connection is not configured")
        try:
            async with httpx.AsyncClient(timeout=30.0, transport=self._transport) as client:
                response = await client.delete(
                    f"{self._host}{MINIMAX_VIDEO_CANCEL_PATH.format(task_id=remote_task_id)}",
                    headers=self._headers(),
                )
        except httpx.TransportError:
            return {"status": "cancelled"}
        data = _json_object(response)
        status = str(data.get("status") or "").lower()
        return {
            "status": "cancelled"
            if response.status_code < 400 and status == "cancelled"
            else "cancelled"
        }

    async def fetch_cost(self, remote_task_id: str) -> dict[str, Any]:
        _ = remote_task_id
        return {"amount": 0.0, "currency": "USD", "units": 1.0}


class MiniMaxImageCompiler:
    def validate(self, intent: Any, model: Any) -> None:
        operation = model.operations.get("image.generate")
        if operation is None or "image.i2i" not in set(operation.capabilities):
            raise ValueError("model does not support image.i2i")
        constraint = operation.reference_constraints.get("reference_image")
        if (
            intent.reference_artifact_id is None
            or constraint is None
            or constraint.min != 1
            or constraint.max != 1
        ):
            raise ValueError("MiniMax image generation requires exactly one reference_image")
        if intent.size not in {None, "1024x1024"}:
            raise ValueError("MiniMax image catalog revision only supports 1024x1024")

    async def compile(
        self, intent: Any, model: Any, references: list[Any], *, invoke_model_value: str
    ) -> Any:
        self.validate(intent, model)
        ref = next((item for item in references if item.role == "reference_image"), None)
        if ref is None or ref.content_url is None:
            raise ValueError("MiniMax reference_image must be an HTTPS URL")
        body, _ = _build_image_body(
            invoke_model_value, prompt=intent.prompt, reference_url=ref.content_url
        )
        from app.providers.runtime import CompiledImageRequest

        fingerprints = [ref.fingerprint] if ref.fingerprint else []
        return CompiledImageRequest(
            provider_type="minimax",
            protocol_profile=MINIMAX_CN_PROFILE,
            model_id=invoke_model_value,
            operation="image.generate",
            wire_request=cast(dict[str, JsonValue], body),
            request_schema_version=model.manifest_version,
            safe_request_summary=cast(
                dict[str, JsonValue],
                _summary(
                    operation="image.i2i.character",
                    model=invoke_model_value,
                    artifact_ids=[str(ref.artifact_id)],
                    fingerprints=fingerprints,
                    schema_version=model.manifest_version,
                ),
            ),
            reference_artifact_ids=[ref.artifact_id],
            reference_fingerprints=fingerprints,
        )


class MiniMaxVideoCompiler:
    def validate(self, intent: Any, model: Any) -> None:
        operation = model.operations.get("video.generate")
        if operation is None or "video.i2v.first_frame" not in set(operation.capabilities):
            raise ValueError("model does not support video.i2v.first_frame")
        frames = [ref for ref in intent.references if ref.role == "first_frame"]
        constraint = operation.reference_constraints.get("first_frame")
        if constraint is None or len(frames) != 1 or constraint.min != 1 or constraint.max != 1:
            raise ValueError("MiniMax video generation requires exactly one first_frame")
        if any(ref.role != "first_frame" for ref in intent.references):
            raise ValueError("MiniMax video catalog revision supports no other reference roles")
        constraints = operation.output_constraints
        if (
            constraints.get("duration_seconds") != 5
            or constraints.get("resolution") != "768P"
            or constraints.get("aspect_ratio") != "adaptive"
            or constraints.get("native_audio") is not False
        ):
            raise ValueError("MiniMax H3 output capability contract is unsupported")
        output = intent.output
        if (
            output.duration_seconds not in {None, 5}
            or output.resolution not in {None, "768P"}
            or output.aspect_ratio not in {"9:16", "16:9"}
            or output.generate_audio not in {None, False}
            or output.seed is not None
        ):
            raise ValueError(
                "MiniMax H3 catalog revision only supports 768P, 5 seconds, "
                "a 9:16 or 16:9 first-frame-inherited ratio, no seed, and no audio"
            )

    async def compile(
        self, intent: Any, model: Any, references: list[Any], *, invoke_model_value: str
    ) -> Any:
        self.validate(intent, model)
        ref = next((item for item in references if item.role == "first_frame"), None)
        if ref is None or ref.content_url is None:
            raise ValueError("MiniMax first_frame must be an HTTPS URL")
        body, _ = _build_video_body(
            invoke_model_value, prompt=intent.prompt, first_frame_url=ref.content_url
        )
        from app.providers.runtime import CompiledVideoRequest

        fingerprints = [ref.fingerprint] if ref.fingerprint else []
        effective_options: dict[str, object] = {
            "aspect_ratio": intent.output.aspect_ratio,
            "duration_seconds": 5,
            "resolution": "768P",
            "generate_audio": False,
        }
        transformations: list[dict[str, object]] = [
            {
                "field": "aspect_ratio",
                "from_value": intent.output.aspect_ratio,
                "to_value": "adaptive",
                "reason": "provider_inherits_aspect_ratio_from_first_frame",
            }
        ]
        if intent.output.duration_seconds is None:
            transformations.append(
                {
                    "field": "duration_seconds",
                    "from_value": None,
                    "to_value": 5,
                    "reason": "provider_applies_documented_default",
                }
            )
        summary = _summary(
            operation="video.i2v.first_frame",
            model=invoke_model_value,
            artifact_ids=[str(ref.artifact_id)],
            fingerprints=fingerprints,
            schema_version=model.manifest_version,
        )
        summary["effective_common_options"] = effective_options
        summary["translation_transformations"] = transformations
        return CompiledVideoRequest(
            provider_type="minimax",
            protocol_profile=MINIMAX_CN_PROFILE,
            model_id=invoke_model_value,
            operation="video.generate",
            wire_request=cast(dict[str, JsonValue], body),
            request_schema_version=model.manifest_version,
            safe_request_summary=cast(
                dict[str, JsonValue],
                summary,
            ),
            reference_artifact_ids=[ref.artifact_id],
            reference_fingerprints=fingerprints,
        )


class MiniMaxRuntime:
    provider = "minimax"
    protocol_profile = MINIMAX_CN_PROFILE

    def __init__(
        self,
        *,
        connection: Any | None = None,
        settings: Settings | None = None,
        host: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._host = (host or self._settings.minimax_base_url).strip().rstrip("/")
        self._key = self._settings.minimax_api_key.strip()
        self._enabled = self._settings.minimax_enabled
        self._transport = transport

    def _configured(self) -> bool:
        return bool(self._enabled and self._key)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"}

    async def submit_image(self, request: Any) -> Any:
        from app.providers.runtime import ProviderResumeToken, SubmissionResult

        if not self._configured():
            raise RuntimeError("MiniMax connection is not configured")
        try:
            response = await _post_json(
                self._host,
                MINIMAX_IMAGE_PATH,
                headers=self._headers(),
                body=request.wire_request,
                timeout=150.0,
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
        uri = _image_result_url(data)
        if response.status_code >= 400 or not _api_succeeded(data) or uri is None:
            return SubmissionResult(
                status="failed",
                error_code=_error_code(response.status_code)
                if response.status_code >= 400
                else "PROVIDER_RESPONSE_INVALID",
                retry_after_seconds=_retry_after_seconds(response),
                http_status=response.status_code,
                request_fingerprint=_request_fingerprint(request.wire_request),
                request_summary=request.safe_request_summary,
            )
        remote_task_id = str(data.get("id") or "minimax-image")
        token = ProviderResumeToken(
            provider_type="minimax",
            protocol_profile=MINIMAX_CN_PROFILE,
            remote_task_id=remote_task_id,
        )
        return SubmissionResult(
            remote_task_id=remote_task_id,
            status="succeeded",
            artifact_uri=uri,
            request_fingerprint=_request_fingerprint(request.wire_request),
            request_summary=request.safe_request_summary,
            resume_token=token,
        )

    async def submit_video(self, request: Any) -> Any:
        from app.providers.runtime import ProviderResumeToken, SubmissionResult

        if not self._configured():
            raise RuntimeError("MiniMax connection is not configured")
        try:
            response = await _post_json(
                self._host,
                MINIMAX_VIDEO_CREATE_PATH,
                headers=self._headers(),
                body=request.wire_request,
                timeout=120.0,
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
        task_id = data.get("task_id")
        if response.status_code >= 400 or not _api_succeeded(data) or not task_id:
            return SubmissionResult(
                status="failed",
                error_code=_error_code(response.status_code)
                if response.status_code >= 400
                else "PROVIDER_RESPONSE_INVALID",
                retry_after_seconds=_retry_after_seconds(response),
                http_status=response.status_code,
                request_fingerprint=_request_fingerprint(request.wire_request),
                request_summary=request.safe_request_summary,
            )
        token = ProviderResumeToken(
            provider_type="minimax",
            protocol_profile=MINIMAX_CN_PROFILE,
            remote_task_id=str(task_id),
        )
        return SubmissionResult(
            remote_task_id=str(task_id),
            status="queued",
            request_fingerprint=_request_fingerprint(request.wire_request),
            request_summary=request.safe_request_summary,
            resume_token=token,
        )

    async def poll_video(self, resume: Any) -> Any:
        from app.providers.runtime import PollResult

        if not self._configured():
            raise RuntimeError("MiniMax connection is not configured")
        try:
            response = await _get_json(
                self._host,
                MINIMAX_VIDEO_QUERY_PATH.format(task_id=resume.remote_task_id),
                headers=self._headers(),
                timeout=60.0,
                transport=self._transport,
            )
        except httpx.TransportError:
            return PollResult(status="running", error_code="PROVIDER_POLL_TRANSIENT")
        data = _json_object(response)
        if response.status_code >= 400 or not _api_succeeded(data):
            if response.status_code == 429 or response.status_code >= 500:
                return PollResult(
                    status="running",
                    http_status=response.status_code,
                    error_code="PROVIDER_RATE_LIMITED"
                    if response.status_code == 429
                    else "PROVIDER_POLL_TRANSIENT",
                )
            return PollResult(
                status="failed",
                http_status=response.status_code,
                error_code=_error_code(response.status_code),
            )
        raw = str(_video_task(data).get("status") or "").lower()
        status = {
            "queued": "queued",
            "running": "running",
            "succeeded": "succeeded",
            "failed": "failed",
            "cancelled": "cancelled",
        }.get(raw, "running")
        return PollResult(
            status=status,
            artifact_uri=_video_result_url(data),
            error_code="PROVIDER_TASK_FAILED" if status == "failed" else None,
        )

    async def cancel_video(self, resume: Any) -> Any:
        from app.providers.runtime import CancelResult

        if not self._configured():
            raise RuntimeError("MiniMax connection is not configured")
        try:
            async with httpx.AsyncClient(timeout=30.0, transport=self._transport) as client:
                await client.delete(
                    f"{self._host}{MINIMAX_VIDEO_CANCEL_PATH.format(task_id=resume.remote_task_id)}",
                    headers=self._headers(),
                )
        except httpx.TransportError:
            pass
        return CancelResult(status="cancelled")

    async def fetch_cost(self, resume: Any) -> Any:
        from app.providers.runtime import CostResult

        _ = resume
        return CostResult(amount=0.0, currency="USD", units=1.0)


def _minimax_runtime_factory(
    *,
    connection: Any | None = None,
    settings: Settings | None = None,
    host: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> MiniMaxRuntime:
    return MiniMaxRuntime(connection=connection, settings=settings, host=host, transport=transport)


def _minimax_compiler_factory() -> tuple[MiniMaxImageCompiler, MiniMaxVideoCompiler]:
    return MiniMaxImageCompiler(), MiniMaxVideoCompiler()
