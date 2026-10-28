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
from urllib.parse import quote, urlsplit

import httpx
from pydantic import JsonValue

from app.config import Settings, get_settings
from app.providers.egress import guarded_provider_transport
from app.providers.http_client import provider_http_client
from app.providers.manifest import ModelCapabilityManifest
from app.providers.runtime import (
    PROVIDER_CONTENT_URI,
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
OPENAI_IMAGES_PROFILE = "openai_images_v2"
OPENAI_MEDIA_DEFAULT_HOST = "https://api.openai.com/v1"


def _base_url(host: str) -> str:
    value = host.strip().rstrip("/")
    if not value:
        raise ValueError("OpenAI-compatible media base URL is empty")
    return value if value.endswith("/v1") else f"{value}/v1"


def normalize_images_base_url(host: str) -> str:
    value = host.strip().rstrip("/")
    if value.endswith("/images/generations"):
        value = value[: -len("/images/generations")]
        if not urlsplit(value).path:
            raise ValueError("Images operation URL requires an explicit API base prefix")
        return value
    return value if urlsplit(value).path else f"{value}/v1"


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
        protocol_profile: str = OPENAI_MEDIA_PROFILE,
    ) -> None:
        cfg = settings or get_settings()
        self._settings = cfg
        self.protocol_profile = protocol_profile
        self._key = cfg.openai_compatible_media_api_key.strip()
        normalize = (
            normalize_images_base_url if protocol_profile == OPENAI_IMAGES_PROFILE else _base_url
        )
        self._host = normalize(host or cfg.openai_compatible_media_base_url)
        self._transport = transport or guarded_provider_transport(settings=self._settings)
        self._image_model = cfg.openai_compatible_media_image_model.strip()
        self._video_model = cfg.openai_compatible_media_video_model.strip()

    def configured(self) -> bool:
        return bool(
            self._settings.openai_compatible_media_enabled
            and (
                self._key
                or self.protocol_profile == OPENAI_IMAGES_PROFILE
                and self._settings.openai_compatible_media_auth_mode == "none"
            )
        )

    def _headers(self) -> dict[str, str]:
        if (
            self.protocol_profile == OPENAI_IMAGES_PROFILE
            and self._settings.openai_compatible_media_auth_mode == "none"
        ):
            return {}
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
            "remote_task_id": None,
            "artifact_uri": image_url,
            "http_status": response.status_code,
        }

    async def _post_image(
        self,
        payload: dict[str, Any],
        image_bytes: bytes | None,
        image_mime: str,
    ) -> httpx.Response:
        if self.protocol_profile == OPENAI_IMAGES_PROFILE:
            from app.providers.image_results import bounded_response

            if image_bytes is not None:
                raise ValueError("this Images profile has no image-edit contract")
            async with provider_http_client(
                timeout=self._settings.openai_compatible_media_timeout_seconds,
                transport=self._transport,
            ) as client:
                return await bounded_response(
                    client,
                    "POST",
                    f"{self._host}/images/generations",
                    headers=self._headers(),
                    json=payload,
                )
        async with provider_http_client(
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
                key: str(value) for key, value in payload.items() if key != "reference_artifact_ids"
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
        *,
        multipart_text: bool = False,
    ) -> httpx.Response:
        async with provider_http_client(
            timeout=self._settings.openai_compatible_media_timeout_seconds,
            transport=self._transport,
        ) as client:
            if image_bytes is None:
                if multipart_text:
                    return await client.post(
                        f"{self._host}/videos",
                        headers=self._headers(),
                        files={key: (None, str(value)) for key, value in payload.items()},
                    )
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
        async with provider_http_client(
            timeout=self._settings.openai_compatible_media_timeout_seconds,
            transport=self._transport,
        ) as client:
            response = await client.get(
                f"{self._host}/videos/{quote(remote_task_id, safe='')}",
                headers=self._headers(),
            )
        data = _json_object(response)
        status = _status(data.get("status"))
        artifact_uri = _first_url(data)
        if (
            status == "succeeded"
            and response.status_code < 400
            and (
                self._host.startswith("http://")
                or artifact_uri is None
                or not artifact_uri.startswith("https://")
            )
        ):
            artifact_uri = PROVIDER_CONTENT_URI
        return {
            "status": status if response.status_code < 400 else "failed",
            "progress": float(data.get("progress") or 0),
            "artifact_uri": artifact_uri,
            "http_status": response.status_code,
            "error_code": None if response.status_code < 400 else _error_code(response.status_code),
        }


class OpenAICompatibleImageCompiler:
    workbench_option_fields = frozenset({"size", "aspect_ratio"})
    # The unified delivery layer hands this provider family stored media
    # bytes (data-URI / b64 branches); the URL branch exists for callers
    # that already hold a public URL, which the Workbench Worker is not.
    reference_transport = "bytes"

    def __init__(self, protocol_profile: str = OPENAI_MEDIA_PROFILE):
        self.protocol_profile = protocol_profile

    def validate(self, intent: Any, model: ModelCapabilityManifest) -> None:
        operation = model.operations.get("image.generate")
        if operation is None:
            raise ValueError("model does not support image.generate")
        if model.protocol_profile != self.protocol_profile:
            raise ValueError("image contract does not match this compiler")
        if self.protocol_profile == OPENAI_IMAGES_PROFILE and (
            intent.single_reference_id() is not None
            or intent.size not in {None, "1024x1024"}
            or intent.aspect_ratio not in {None, "1:1"}
            or intent.seed is not None
            or not intent.prompt.strip()
            or len(intent.prompt) > 4096
        ):
            raise ValueError("Images v2 supports only one 1024x1024 text-to-image output")
        required = "image.i2i" if intent.single_reference_id() is not None else "image.t2i"
        if required not in operation.capabilities:
            raise ValueError(f"model does not support {required}")
        constraint = operation.reference_constraints.get("reference_image")
        if intent.single_reference_id() is not None and (constraint is None or constraint.max < 1):
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
        if self.protocol_profile == OPENAI_IMAGES_PROFILE and references:
            raise ValueError("Images v2 does not accept reference media")
        resolved = [ref for ref in references if ref.role == "reference_image"]
        if len(resolved) > 1:
            raise ValueError("OpenAI-compatible image compiler accepts one reference_image")
        ref = resolved[0] if resolved else None
        if intent.single_reference_id() is not None and (
            ref is None or ref.artifact_id != intent.single_reference_id()
        ):
            raise ValueError("resolved reference_image does not match the image intent")
        body: dict[str, JsonValue] = {
            "model": invoke_model_value,
            "prompt": intent.prompt,
            "size": intent.size or "1024x1024",
            "n": 1,
            "response_format": "url",
        }
        if self.protocol_profile == OPENAI_IMAGES_PROFILE:
            body.pop("response_format")
        if intent.aspect_ratio is not None and self.protocol_profile != OPENAI_IMAGES_PROFILE:
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
            protocol_profile=self.protocol_profile,
            model_id=invoke_model_value,
            operation="image.generate",
            wire_request=body,
            request_schema_version=model.manifest_version,
            safe_request_summary=cast(dict[str, JsonValue], summary),
            reference_artifact_ids=[ref.artifact_id] if ref is not None else [],
            reference_fingerprints=[ref.fingerprint] if ref is not None and ref.fingerprint else [],
        )


class OpenAICompatibleVideoCompiler:
    workbench_option_fields = frozenset({"duration_seconds", "resolution", "aspect_ratio"})
    # Same as the image compiler: every reference-consuming branch of this
    # family (FL2VA / Ref2VA / first-frame I2V) requires stored bytes.
    reference_transport = "bytes"
    # Trusted catalog-contract compiler registrations. Remote model names never
    # select a wire task; unknown revisions cannot inherit advanced H3 modes.
    _wire_contracts = {
        ("@contract/sglang-h3-t2v-v1", "v2"): "t2va",
        ("@contract/sglang-h3-ref2va-v1", "v3"): "ref2va",
        ("@contract/sglang-h3-fl2va-v1", "v2"): "fl2va",
    }

    def _wire_contract(self, model: ModelCapabilityManifest) -> str | None:
        return self._wire_contracts.get((model.model_id, model.model_revision))

    def validate(self, intent: Any, model: ModelCapabilityManifest) -> None:
        operation = model.operations.get("video.generate")
        if operation is None:
            raise ValueError("model does not support video.generate")
        text_only = intent.mode_id == "text_to_video"
        reference_mode = intent.mode_id == "omni_reference"
        wire_contract = self._wire_contract(model)
        if wire_contract is None and model.model_id in {key[0] for key in self._wire_contracts}:
            raise ValueError("SGLang contract revision has no registered compiler")
        fl2va = wire_contract == "fl2va"
        frame_modes = {"first_frame", "last_frame", "first_last_frame"}
        if reference_mode:
            if not any(
                capability in operation.capabilities
                for capability in (
                    "video.reference.image",
                    "video.reference.video",
                    "video.reference.audio",
                )
            ):
                raise ValueError("model does not support reference video generation")
        else:
            required = (
                ["video.t2v"]
                if text_only
                else ["video.i2v.first_frame", "video.i2v.last_frame"]
                if intent.mode_id == "first_last_frame"
                else ["video.i2v.last_frame"]
                if intent.mode_id == "last_frame"
                else ["video.i2v.first_frame"]
            )
            if not set(required) <= set(operation.capabilities):
                raise ValueError(f"model does not support {required}")
        if text_only and wire_contract not in {"t2va", "fl2va"}:
            raise ValueError("text_to_video requires the SGLang H3 T2VA contract")
        if reference_mode and wire_contract != "ref2va":
            raise ValueError("omni_reference requires the SGLang H3 Ref2VA contract")
        if intent.mode_id in {"last_frame", "first_last_frame"} and not fl2va:
            raise ValueError("last-frame generation requires the SGLang H3 FL2VA contract")
        if fl2va and intent.mode_id not in frame_modes | {"text_to_video"}:
            raise ValueError("FL2VA does not support this input mode")
        if text_only and intent.references:
            raise ValueError("text_to_video does not accept artifact references")
        if not (reference_mode or fl2va) and intent.output.generate_audio not in {None, False}:
            raise ValueError("OpenAI-compatible video contract does not support native audio")
        if (reference_mode or fl2va) and intent.output.generate_audio is False:
            raise ValueError("SGLang H3 generates native audio; it cannot be disabled")
        if wire_contract is not None and intent.output.duration_seconds not in {None, 5}:
            raise ValueError("SGLang H3 contract supports 5-second output")
        if (reference_mode or fl2va) and intent.output.aspect_ratio not in {None, "9:16", "16:9"}:
            raise ValueError("SGLang H3 contract requires 9:16 or 16:9")

    async def compile(
        self,
        intent: Any,
        model: ModelCapabilityManifest,
        references: list[Any],
        *,
        invoke_model_value: str,
    ) -> CompiledVideoRequest:
        self.validate(intent, model)
        if self._wire_contract(model) == "fl2va":
            expected_roles = {
                "text_to_video": [],
                "first_frame": ["first_frame"],
                "last_frame": ["last_frame"],
                "first_last_frame": ["first_frame", "last_frame"],
            }[intent.mode_id]
            if [ref.role for ref in intent.references] != expected_roles or len(references) != len(
                expected_roles
            ):
                raise ValueError("FL2VA references do not match the selected frame mode")
            frame_conditions: list[JsonValue] = []
            for expected, ref, role in zip(
                intent.references, references, expected_roles, strict=True
            ):
                if expected.artifact_id != ref.artifact_id or ref.role != role:
                    raise ValueError("FL2VA resolved frame identity or order changed")
                if not ref.mime_type.startswith("image/") or not ref.content_bytes:
                    raise ValueError("FL2VA requires stored image bytes")
                if len(ref.content_bytes) > 32 * 1024 * 1024:
                    raise ValueError("FL2VA frame exceeds the media limit")
                encoded = base64.b64encode(ref.content_bytes).decode("ascii")
                frame_conditions.append(
                    {
                        "type": "image",
                        "uri": f"data:{ref.mime_type};base64,{encoded}",
                        "role": "keyframe",
                        "frame_index": 0 if role == "first_frame" else -1,
                    }
                )
            duration = intent.output.duration_seconds or 5
            frame_body: dict[str, JsonValue] = {
                "model": invoke_model_value,
                "prompt": intent.prompt,
                "seconds": duration,
                "task": "t2va" if not frame_conditions else "fl2va",
                "conditions": frame_conditions,
                "target": {
                    "short_edge": 768,
                    "aspect_ratio": intent.output.aspect_ratio or "9:16",
                    "duration_seconds": float(duration),
                },
                "num_outputs_per_prompt": 1,
                "num_inference_steps": 50,
                "flow_shift": 12.0,
                "audio_flow_shift": 3.0,
            }
            return CompiledVideoRequest(
                provider_type=OPENAI_MEDIA_PROVIDER,
                protocol_profile=OPENAI_MEDIA_PROFILE,
                model_id=invoke_model_value,
                operation="video.generate",
                wire_request=frame_body,
                request_schema_version=model.manifest_version,
                safe_request_summary={
                    "operation": "video.generate",
                    "model": invoke_model_value,
                    "reference_count": len(references),
                    "duration_seconds": duration,
                    "input_mode": intent.mode_id,
                    "request_schema_version": model.manifest_version,
                },
                reference_artifact_ids=[ref.artifact_id for ref in references],
                reference_fingerprints=[ref.fingerprint for ref in references if ref.fingerprint],
            )
        if intent.mode_id == "omni_reference":
            if not intent.references or len(intent.references) != len(references):
                raise ValueError("Ref2VA requires resolved artifact references")
            limits = model.operations["video.generate"].reference_media_limits
            if limits is not None:
                limits.validate_metadata([(ref.role, ref.duration_seconds) for ref in references])
            types = {
                "reference_image": ("image/", "image"),
                "reference_video": ("video/", "video"),
                "reference_audio": ("audio/", "audio"),
            }
            counts: dict[str, int] = {}
            conditions: list[JsonValue] = []
            total_bytes = 0
            for expected, ref in zip(intent.references, references, strict=True):
                if expected.artifact_id != ref.artifact_id or expected.role != ref.role:
                    raise ValueError("Ref2VA resolved reference order or identity changed")
                if ref.role not in types:
                    raise ValueError(f"Ref2VA does not accept role {ref.role}")
                mime_prefix, media_type = types[ref.role]
                capability = f"video.reference.{media_type}"
                if capability not in model.operations["video.generate"].capabilities:
                    raise ValueError(f"model does not support {capability}")
                if not ref.mime_type.startswith(mime_prefix):
                    raise ValueError(f"Ref2VA {ref.role} has incompatible media type")
                counts[ref.role] = counts.get(ref.role, 0) + 1
                constraint = model.operations["video.generate"].reference_constraints[ref.role]
                if counts[ref.role] > constraint.max:
                    raise ValueError(f"Ref2VA accepts at most {constraint.max} {ref.role}")
                if ref.content_bytes is None:
                    raise ValueError("Ref2VA requires stored reference bytes")
                total_bytes += len(ref.content_bytes)
                if not ref.content_bytes or total_bytes > 128 * 1024 * 1024:
                    raise ValueError("Ref2VA reference bytes exceed the media limit")
                encoded = base64.b64encode(ref.content_bytes).decode("ascii")
                uri = f"data:{ref.mime_type};base64,{encoded}"
                conditions.append(
                    {
                        "type": media_type,
                        "uri": uri,
                        "role": "reference",
                    }
                )
            if len(conditions) > 12:
                raise ValueError("Ref2VA accepts at most 12 references in total")
            duration = intent.output.duration_seconds or 5
            ref_body: dict[str, JsonValue] = {
                "model": invoke_model_value,
                "prompt": intent.prompt,
                "seconds": duration,
                "task": "ref2va",
                "conditions": conditions,
                "target": {
                    "short_edge": 768,
                    "aspect_ratio": intent.output.aspect_ratio or "9:16",
                    "duration_seconds": float(duration),
                },
                "num_outputs_per_prompt": 1,
                "num_inference_steps": 50,
                "flow_shift": 12.0,
                "audio_flow_shift": 3.0,
            }
            return CompiledVideoRequest(
                provider_type=OPENAI_MEDIA_PROVIDER,
                protocol_profile=OPENAI_MEDIA_PROFILE,
                model_id=invoke_model_value,
                operation="video.generate",
                wire_request=ref_body,
                request_schema_version=model.manifest_version,
                safe_request_summary={
                    "operation": "video.generate",
                    "model": invoke_model_value,
                    "reference_count": len(references),
                    "duration_seconds": duration,
                    "input_mode": "omni_reference",
                    "request_schema_version": model.manifest_version,
                },
                reference_artifact_ids=[ref.artifact_id for ref in references],
                reference_fingerprints=[ref.fingerprint for ref in references if ref.fingerprint],
            )
        if intent.mode_id == "text_to_video":
            if references:
                raise ValueError("text_to_video cannot resolve artifact references")
            body: dict[str, JsonValue] = {
                "model": invoke_model_value,
                "prompt": intent.prompt,
                "seconds": intent.output.duration_seconds or 5,
                "size": intent.output.resolution
                or ("720x1280" if intent.output.aspect_ratio == "9:16" else "1280x720"),
                "extra_body": json.dumps({"task": "t2va", "conditions": []}),
            }
            return CompiledVideoRequest(
                provider_type=OPENAI_MEDIA_PROVIDER,
                protocol_profile=OPENAI_MEDIA_PROFILE,
                model_id=invoke_model_value,
                operation="video.generate",
                wire_request=body,
                request_schema_version=model.manifest_version,
                safe_request_summary={
                    "operation": "video.generate",
                    "model": invoke_model_value,
                    "reference_count": 0,
                    "duration_seconds": body["seconds"],
                    "input_mode": "text_to_video",
                    "transport": "multipart_text",
                    "request_schema_version": model.manifest_version,
                },
                reference_artifact_ids=[],
                reference_fingerprints=[],
            )
        expected = next((ref for ref in intent.references if ref.role == "first_frame"), None)
        resolved = [ref for ref in references if ref.role == "first_frame"]
        if (
            expected is None
            or len(resolved) != 1
            or resolved[0].artifact_id != expected.artifact_id
        ):
            raise ValueError("video intent first_frame was not resolved exactly once")
        ref = resolved[0]
        body = {
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
        protocol_profile: str = OPENAI_MEDIA_PROFILE,
    ) -> None:
        self.protocol_profile = protocol_profile
        self._settings = settings or get_settings()
        self._client = OpenAICompatibleMediaClient(
            self._settings,
            host=host or getattr(connection, "base_url", None),
            transport=transport,
            protocol_profile=protocol_profile,
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
        if self.protocol_profile == OPENAI_IMAGES_PROFILE:
            from app.providers.image_results import image_result

            if (
                set(payload) != {"model", "prompt", "size", "n"}
                or payload.get("size") != "1024x1024"
                or type(payload.get("n")) is not int
                or payload.get("n") != 1
                or not isinstance(payload.get("prompt"), str)
                or not str(payload["prompt"]).strip()
                or len(str(payload["prompt"])) > 4096
            ):
                return SubmissionResult(
                    status="failed",
                    error_code="PROVIDER_REQUEST_REJECTED",
                    request_summary=request.safe_request_summary,
                )

            try:
                response = await self._client._post_image(payload, image_bytes, image_mime)
                if response.status_code >= 400:
                    uncertain = response.status_code in {408, 429} or response.status_code >= 500
                    return SubmissionResult(
                        status="unknown_submission" if uncertain else "failed",
                        error_code="PROVIDER_SUBMISSION_UNKNOWN"
                        if uncertain
                        else _error_code(response.status_code),
                        http_status=response.status_code,
                        request_summary=request.safe_request_summary,
                    )
                async with provider_http_client(
                    timeout=self._settings.openai_compatible_media_timeout_seconds,
                    transport=self._client._transport,
                ) as client:
                    content = await image_result(
                        response,
                        origin=self._client._host,
                        client=client,
                        headers=self._client._headers(),
                    )
                return SubmissionResult(
                    status="succeeded",
                    artifact_bytes=content,
                    http_status=response.status_code,
                    request_summary=request.safe_request_summary,
                    request_fingerprint=_fingerprint(request.wire_request),
                )
            except (httpx.HTTPError, ValueError) as exc:
                return SubmissionResult(
                    status="unknown_submission",
                    error_code="PROVIDER_PROTOCOL_MISMATCH",
                    error=type(exc).__name__,
                    request_summary=request.safe_request_summary,
                )
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
            response = await self._client._post_video(
                payload,
                image_bytes,
                image_mime,
                multipart_text=(
                    request.safe_request_summary.get("transport") == "multipart_text"
                    or (
                        request.safe_request_summary.get("input_mode") == "text_to_video"
                        and "extra_body" in payload
                    )
                ),
            )
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

    async def fetch_artifact(self, resume: ProviderResumeToken) -> bytes:
        """Fetch only this connection's completed video, never an arbitrary result URL."""
        self._configured()
        url = f"{self._client._host}/videos/{quote(resume.remote_task_id, safe='')}/content"
        async with (
            provider_http_client(
                timeout=self._settings.openai_compatible_media_timeout_seconds,
                transport=self._client._transport,
            ) as client,
            client.stream("GET", url, headers=self._client._headers()) as response,
        ):
            if response.is_redirect:
                raise ValueError("provider content redirects are not allowed")
            response.raise_for_status()
            body = bytearray()
            async for chunk in response.aiter_bytes(1024 * 1024):
                body.extend(chunk)
                if len(body) > 512 * 1024 * 1024:
                    raise ValueError("provider content exceeds media limit")
            return bytes(body)

    async def cancel_video(self, resume: ProviderResumeToken) -> CancelResult:
        self._configured()
        async with provider_http_client(
            timeout=self._settings.openai_compatible_media_timeout_seconds,
            transport=self._client._transport,
        ) as client:
            response = await client.delete(
                f"{self._client._host}/videos/{quote(resume.remote_task_id, safe='')}",
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


def _openai_images_runtime_factory(**kwargs: Any) -> OpenAICompatibleMediaRuntime:
    return OpenAICompatibleMediaRuntime(protocol_profile=OPENAI_IMAGES_PROFILE, **kwargs)


def _openai_images_compiler_factory() -> tuple[OpenAICompatibleImageCompiler, None]:
    return OpenAICompatibleImageCompiler(OPENAI_IMAGES_PROFILE), None
