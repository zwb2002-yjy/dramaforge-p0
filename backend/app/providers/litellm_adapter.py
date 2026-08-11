"""Generic LiteLLM ModelAdapter (spec §24–§28, §113).

A single adapter that submits any capability through a LiteLLM Gateway's
OpenAI-compatible HTTP surface. It is *generic*: the wire behavior comes from the
model's :class:`ModelBackendBinding` (gateway_model, api_mode) carried in the
manifest metadata — there is one adapter, not per-provider text/image/video
adapters. P0 wires ``text.generate`` (``api_mode="chat"``); image/video gateway
modes are reserved for the LiteLLM media plan.

No ``litellm`` pip dependency: the gateway is a separate process (like the
existing hub adapters) and the app talks to it over httpx.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.config import Settings, get_settings
from app.providers.capabilities import Capability
from app.providers.contracts.common import (
    ExecutionContext,
    GenerationStatus,
    ProviderCancelResult,
    ProviderCostResult,
    ProviderCreateResult,
    ProviderPollResult,
    ResolvedArtifact,
)
from app.providers.contracts.text import TextGenerateRequest
from app.providers.manifest import ModelManifest
from app.providers.model_profiles.models import ModelBackendBinding
from app.providers.translation import (
    EffectiveRequest,
    TranslationReport,
    TranslationResult,
)

_DEFAULT_TIMEOUT_S = 120.0
_RETRYABLE_STATUSES = {408, 429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 3


class LiteLLMModelAdapter:
    """V3 ModelAdapter over a LiteLLM Gateway (OpenAI-compatible)."""

    provider_id = "litellm"

    def __init__(
        self,
        manifest: ModelManifest,
        *,
        settings: Settings | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._manifest = manifest
        self._settings_override = settings
        self._transport = transport
        raw_backend = manifest.metadata.get("backend") or {}
        self._backend = ModelBackendBinding.model_validate(raw_backend)
        self.model_id = manifest.id
        self.calls: list[dict[str, Any]] = []

    @property
    def _settings(self) -> Settings:
        # Read lazily so tests can flip env vars + clear the settings cache.
        return self._settings_override or get_settings()

    @property
    def manifest(self) -> ModelManifest:
        return self._manifest

    @property
    def backend(self) -> ModelBackendBinding:
        return self._backend

    def configured(self) -> bool:
        return bool(
            self._settings.litellm_gateway_url.strip()
            and self._settings.litellm_api_key.strip()
        )

    # ------------------------------------------------------------------
    # translate (pure, no I/O)
    # ------------------------------------------------------------------

    async def translate(
        self,
        capability: Capability,
        request: Any,
        resolved_artifacts: dict[str, ResolvedArtifact],
    ) -> TranslationResult:
        payload, _ = self._build_payload(capability, request)
        requested_options: dict[str, Any] = {}
        if isinstance(request, TextGenerateRequest):
            requested_options = request.model_dump(
                exclude={"prompt", "messages", "native_options"}
            )
        return TranslationResult(
            capability=capability,
            effective_request=EffectiveRequest(
                capability=capability,
                model_id=self.model_id,
                inputs={
                    "prompt": getattr(request, "prompt", "") or "",
                },
                common_options=requested_options,
                native_options=dict(getattr(request, "native_options", {}) or {}),
            ),
            native_request=payload,
            translation_report=TranslationReport(
                requested_options=requested_options,
                effective_options=requested_options,
            ),
        )

    # ------------------------------------------------------------------
    # create / poll / cancel / cost
    # ------------------------------------------------------------------

    async def create(
        self,
        capability: Capability,
        request: Any,
        context: ExecutionContext,
    ) -> ProviderCreateResult:
        if capability is not Capability.TEXT_GENERATE:
            from app.providers.errors import UnsupportedCapabilityError

            raise UnsupportedCapabilityError(capability)
        if not self.configured():
            from app.providers.model_profiles.errors import profile_model_not_configured

            raise profile_model_not_configured(self.model_id)
        payload, _ = self._build_payload(capability, request)
        url = self._chat_url()
        headers = {
            "Authorization": f"Bearer {self._settings.litellm_api_key.strip()}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(
            timeout=_DEFAULT_TIMEOUT_S,
            transport=self._transport,
            proxy=None,
            trust_env=False,
        ) as client:
            last_error = "litellm request failed"
            for attempt in range(1, _MAX_ATTEMPTS + 1):
                self.calls.append(
                    {"op": "create", "capability": str(capability), "attempt": attempt}
                )
                try:
                    resp = await client.post(url, headers=headers, json=payload)
                    try:
                        data = resp.json()
                    except Exception:
                        data = {"raw_status": resp.status_code, "text": resp.text[:200]}
                    if resp.status_code < 400:
                        text_out = _extract_completion_text(data)
                        return ProviderCreateResult(
                            status=GenerationStatus.SUCCEEDED,
                            provider_metadata={
                                "text": text_out,
                                "usage": data.get("usage") if isinstance(data, dict) else {},
                                "model": (
                                    str(data.get("model") or "") if isinstance(data, dict) else ""
                                ),
                            },
                        )
                    last_error = f"litellm http {resp.status_code}: {str(data)[:160]}"
                    if resp.status_code not in _RETRYABLE_STATUSES:
                        break
                except (
                    httpx.TimeoutException,
                    httpx.NetworkError,
                    httpx.RemoteProtocolError,
                ) as exc:
                    last_error = f"litellm {type(exc).__name__}: {exc}"
                if attempt < _MAX_ATTEMPTS:
                    import asyncio

                    await asyncio.sleep(min(2.0 ** (attempt - 1), 4.0))
            return ProviderCreateResult(
                status=GenerationStatus.FAILED,
                provider_metadata={"error": last_error},
            )

    async def poll(
        self,
        remote_task_id: str,
        context: ExecutionContext,
    ) -> ProviderPollResult:
        # text.generate is synchronous; nothing to poll.
        return ProviderPollResult(status=GenerationStatus.SUCCEEDED)

    async def cancel(
        self,
        remote_task_id: str,
        context: ExecutionContext,
    ) -> ProviderCancelResult:
        return ProviderCancelResult(status=GenerationStatus.CANCELLED, accepted=False)

    async def fetch_cost(
        self,
        remote_task_id: str,
        context: ExecutionContext,
    ) -> ProviderCostResult:
        return ProviderCostResult(currency="USD", amount=None)

    # ------------------------------------------------------------------
    # payload building
    # ------------------------------------------------------------------

    def _build_payload(
        self, capability: Capability, request: Any
    ) -> tuple[dict[str, Any], str]:
        if capability is not Capability.TEXT_GENERATE:
            from app.providers.errors import UnsupportedCapabilityError

            raise UnsupportedCapabilityError(capability)
        if not isinstance(request, TextGenerateRequest):
            from app.providers.errors import InvalidOptionCombinationError

            raise InvalidOptionCombinationError(
                "text.generate requires a TextGenerateRequest"
            )
        messages: list[dict[str, str]] = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        if request.messages:
            messages.extend(
                {"role": message.role, "content": message.content}
                for message in request.messages
            )
        elif request.prompt:
            messages.append({"role": "user", "content": request.prompt})
        if not messages:
            messages.append({"role": "user", "content": ""})
        payload: dict[str, Any] = {
            "model": self._backend.gateway_model,
            "messages": messages,
        }
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.tools:
            payload["tools"] = request.tools
        if request.response_format:
            payload["response_format"] = request.response_format
        payload.update(request.native_options)
        return payload, "chat"

    def _chat_url(self) -> str:
        base = self._settings.litellm_gateway_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"


def _extract_completion_text(data: Any) -> str:
    if not isinstance(data, dict):
        return str(data)[:2000]
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict) and message.get("content"):
                return str(message["content"])
            if first.get("text"):
                return str(first["text"])
    if isinstance(data.get("content"), str):
        return str(data["content"])
    return str(data)[:2000]
