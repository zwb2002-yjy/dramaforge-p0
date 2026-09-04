"""Generic LiteLLM ModelAdapter (spec §24–§28, §113; fix spec §66–§71).

A single adapter that submits any capability through a LiteLLM Gateway's
OpenAI-compatible HTTP surface. It is *generic*: the wire behavior comes from the
model's :class:`ModelBackendBinding` (gateway_model, api_mode) carried in the
manifest metadata — there is one adapter, not per-provider text/image/video
adapters. P0 wires ``text.generate`` (``api_mode="chat"``); image/video gateway
modes are reserved for the LiteLLM media plan.

The adapter is a V3 *semantic* adapter: it maps ``TextGenerateRequest`` →
OpenAI-compatible payload → ``ProviderCreateResult``. ALL HTTP to the official
LiteLLM Proxy runs through :class:`LiteLLMGatewayClient` (spec §67) — the
adapter never opens an httpx session and never retries: LiteLLM's Router owns
provider/deployment retry/fallback/cooldown (spec §5/§95), and a read timeout
after submit escalates to ``SUBMIT_UNKNOWN`` because the request may have been
billed (spec §64/§65).

No ``litellm`` pip dependency: the gateway is a separate process and the app
talks to it over HTTP.
"""

from __future__ import annotations

from typing import Any

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
from app.providers.errors import ProviderError
from app.providers.litellm_gateway.client import LiteLLMGatewayClient
from app.providers.manifest import ModelManifest
from app.providers.model_profiles.models import ModelBackendBinding
from app.providers.translation import (
    EffectiveRequest,
    TranslationReport,
    TranslationResult,
)


class LiteLLMModelAdapter:
    """V3 ModelAdapter over a LiteLLM Gateway (OpenAI-compatible)."""

    provider_id = "litellm"

    def __init__(
        self,
        manifest: ModelManifest,
        *,
        settings: Settings | None = None,
        transport: Any = None,
        client: LiteLLMGatewayClient | None = None,
    ) -> None:
        self._manifest = manifest
        self._settings_override = settings
        self._transport = transport
        self._client_override = client
        raw_backend = manifest.metadata.get("backend") or {}
        self._backend = ModelBackendBinding.model_validate(raw_backend)
        self.model_id = manifest.id
        self.calls: list[dict[str, Any]] = []

    @property
    def _settings(self) -> Settings:
        # Read lazily so tests can flip env vars + clear the settings cache.
        return self._settings_override or get_settings()

    @property
    def _client(self) -> LiteLLMGatewayClient:
        if self._client_override is None:
            self._client_override = LiteLLMGatewayClient(
                settings=self._settings_override,
                transport=self._transport,
            )
        return self._client_override

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
        self.calls.append(
            {"op": "create", "capability": str(capability), "attempt": 1}
        )
        try:
            response = await self._client.chat_completion(
                model=self._backend.gateway_model,
                payload=payload,
            )
        except Exception as exc:  # noqa: BLE001 - classified below
            # SUBMIT_UNKNOWN must win over the generic ProviderError branch:
            # SubmissionOutcomeUnknownError IS a ProviderError, but the request
            # may have been billed — surface the ambiguous state (spec §64/§65).
            from app.providers.errors import (
                ProviderErrorCode,
                SubmissionOutcomeUnknownError,
            )

            if isinstance(exc, SubmissionOutcomeUnknownError):
                return ProviderCreateResult(
                    status=GenerationStatus.SUBMIT_UNKNOWN,
                    provider_metadata={
                        "error_code": str(ProviderErrorCode.SUBMISSION_OUTCOME_UNKNOWN),
                        "error": exc.message,
                    },
                )
            if isinstance(exc, ProviderError):
                # Classified gateway failure (spec §63): 401→auth, 404→model,
                # 429→rate limit, 5xx/connect→gateway unavailable, 400 heuristics.
                return ProviderCreateResult(
                    status=GenerationStatus.FAILED,
                    provider_metadata={
                        "error_code": str(exc.code),
                        "error": exc.message,
                    },
                )
            return ProviderCreateResult(
                status=GenerationStatus.FAILED,
                provider_metadata={
                    "error_code": str(ProviderErrorCode.UNKNOWN),
                    "error": f"litellm {type(exc).__name__}: {exc}",
                },
            )
        text_out = _extract_completion_text(response.data)
        metadata: dict[str, Any] = {
            "text": text_out,
            "usage": (
                response.data.get("usage") if isinstance(response.data, dict) else {}
            ),
            "model": (
                str(response.data.get("model") or "") if isinstance(response.data, dict) else ""
            ),
            **response.metadata,
        }
        return ProviderCreateResult(
            status=GenerationStatus.SUCCEEDED,
            provider_metadata=metadata,
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
        # Sync text carries cost in the create result metadata (spec §45);
        # there is no remote task to fetch cost for.
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
        # The gateway model comes from the manifest's ModelBackendBinding; the
        # client injects it as the wire ``model`` (spec §71). DramaForge never
        # hardcodes an upstream provider model here.
        return payload, "chat"


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
