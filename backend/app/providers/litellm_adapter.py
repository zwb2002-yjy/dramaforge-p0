"""Generic LiteLLM ModelAdapter (spec §24–§28, §113; fix spec §66–§71).

A single text adapter uses the internal Proxy's Chat HTTP surface. Its fixed
alias and execution reference come from the selected manifest. Media retains
the existing Compiler/Runtime path and does not use the LLM Proxy.

The adapter is a V3 *semantic* adapter: it maps ``TextGenerateRequest`` →
OpenAI-compatible payload → ``ProviderCreateResult``. ALL HTTP to the official
LiteLLM Proxy runs through :class:`LiteLLMGatewayClient` (spec §67) — the
adapter never opens an httpx session or retries. The client permits only one
proven pre-send DF→Proxy retry, with no Proxy→upstream retry or fallback. A read timeout
after submit escalates to ``SUBMIT_UNKNOWN`` because the request may have been
billed (spec §64/§65).

No ``litellm`` pip dependency: the gateway is a separate process and the app
talks to it over HTTP.
"""

from __future__ import annotations

import json
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
)
from app.providers.contracts.text import TextGenerateRequest, TextToolCall
from app.providers.errors import ProviderError
from app.providers.litellm_gateway.client import LiteLLMGatewayClient
from app.providers.manifest import ModelManifest
from app.providers.model_profiles.models import ModelBackendBinding
from app.providers.runtime import ResolvedReference
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
            self._settings.litellm_gateway_url.strip() and self._settings.litellm_api_key.strip()
        )

    # ------------------------------------------------------------------
    # translate (pure, no I/O)
    # ------------------------------------------------------------------

    async def translate(
        self,
        capability: Capability,
        request: Any,
        resolved_references: list[ResolvedReference],
    ) -> TranslationResult:
        payload, _ = self._build_payload(capability, request)
        requested_options: dict[str, Any] = {}
        if isinstance(request, TextGenerateRequest):
            requested_options = request.model_dump(exclude={"messages", "native_options"})
        return TranslationResult(
            capability=capability,
            effective_request=EffectiveRequest(
                capability=capability,
                model_id=self.model_id,
                inputs={
                    "messages": [message.model_dump(mode="json") for message in request.messages],
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
        reference = self.manifest.metadata.get("gateway_reference")
        if (
            isinstance(reference, dict)
            and context.workspace_id
            and reference.get("workspace_id") != context.workspace_id
        ):
            from app.providers.errors import InvalidOptionCombinationError

            raise InvalidOptionCombinationError(
                "text execution workspace does not own the model reference"
            )
        payload, _ = self._build_payload(capability, request)
        self.calls.append({"op": "create", "capability": str(capability), "attempt": 1})
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
                        **{
                            k: exc.details[k]
                            for k in ("df_proxy_transport_attempts", "df_proxy_failure_phase")
                            if exc.details and k in exc.details
                        },
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
                        **{
                            k: exc.details[k]
                            for k in ("df_proxy_transport_attempts", "df_proxy_failure_phase")
                            if exc.details and k in exc.details
                        },
                    },
                )
            return ProviderCreateResult(
                status=GenerationStatus.FAILED,
                provider_metadata={
                    "error_code": str(ProviderErrorCode.UNKNOWN),
                    "error": f"litellm {type(exc).__name__}: {exc}",
                },
            )
        metadata: dict[str, Any] = {
            "usage": _normalize_usage(response.data.get("usage")),
            "model": (
                str(response.data.get("model") or "") if isinstance(response.data, dict) else ""
            ),
            **response.metadata,
        }
        try:
            metadata.update(_normalize_completion(response.data))
        except ValueError:
            # A received but malformed response must not become text by repr(),
            # or trigger another potentially billed request in this adapter.
            return ProviderCreateResult(
                status=GenerationStatus.FAILED,
                provider_metadata={
                    **metadata,
                    "error_code": "unknown",
                    "error": "LiteLLM returned a malformed model response",
                    "stop_reason": "malformed_response",
                },
            )
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

    def _build_payload(self, capability: Capability, request: Any) -> tuple[dict[str, Any], str]:
        if capability is not Capability.TEXT_GENERATE:
            from app.providers.errors import UnsupportedCapabilityError

            raise UnsupportedCapabilityError(capability)
        if not isinstance(request, TextGenerateRequest):
            from app.providers.errors import InvalidOptionCombinationError

            raise InvalidOptionCombinationError("text.generate requires a TextGenerateRequest")
        messages: list[dict[str, Any]] = []
        for message in request.messages:
            item: dict[str, Any] = {"role": message.role, "content": message.content}
            if message.tool_calls:
                item["tool_calls"] = [call.model_dump(mode="json") for call in message.tool_calls]
            if message.tool_call_id is not None:
                item["tool_call_id"] = message.tool_call_id
            if message.name is not None:
                item["name"] = message.name
            messages.append(item)
        payload: dict[str, Any] = {
            "messages": messages,
        }
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.tools:
            payload["tools"] = request.tools
        if request.tool_choice is not None:
            payload["tool_choice"] = request.tool_choice
        if request.parallel_tool_calls is not None:
            payload["parallel_tool_calls"] = request.parallel_tool_calls
        if request.response_format:
            payload["response_format"] = request.response_format
        payload.update(request.native_options)
        forbidden = {
            "api_base",
            "base_url",
            "api_key",
            "extra_headers",
            "headers",
            "custom_llm_provider",
            "model",
            "extra_body",
            "metadata",
            "stream",
            "num_retries",
            "max_retries",
            "fallbacks",
            "mock_response",
            "messages",
            "tools",
            "tool_choice",
            "parallel_tool_calls",
            "response_format",
        }
        if forbidden.intersection(request.native_options):
            from app.providers.errors import InvalidOptionCombinationError

            raise InvalidOptionCombinationError(
                "text options cannot override transport or execution identity"
            )
        reference = self.manifest.metadata.get("gateway_reference")
        if isinstance(reference, dict):
            payload["metadata"] = {"dramaforge_execution": dict(reference)}
        # The gateway model comes from the manifest's ModelBackendBinding; the
        # client injects it as the wire ``model`` (spec §71). DramaForge never
        # hardcodes an upstream provider model here.
        return payload, "chat"


def _normalize_completion(data: Any) -> dict[str, Any]:
    """Normalize only the chat response fields consumed by text callers."""
    if not isinstance(data, dict):
        raise ValueError("completion must be an object")
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ValueError("completion requires a choice")
    first = choices[0]
    message = first.get("message")
    if not isinstance(message, dict):
        raise ValueError("completion requires an assistant message")
    if message.get("role", "assistant") != "assistant":
        raise ValueError("completion must be an assistant message")
    content = message.get("content")
    if content is None:
        text = ""
    elif isinstance(content, str):
        text = content
    elif isinstance(content, list) and all(
        isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str)
        for part in content
    ):
        text = "".join(part["text"] for part in content)
    else:
        raise ValueError("unsupported completion content")
    raw_calls = message.get("tool_calls")
    if raw_calls is None:
        raw_calls = []
    if not isinstance(raw_calls, list):
        raise ValueError("tool_calls must be an array")
    if len(raw_calls) > 12:
        raise ValueError("too many tool calls")
    calls: list[dict[str, Any]] = []
    call_ids: set[str] = set()
    for raw_call in raw_calls:
        if not isinstance(raw_call, dict) or raw_call.get("type") != "function":
            raise ValueError("unsupported tool call")
        call = TextToolCall.model_validate(raw_call)
        if call.id in call_ids:
            raise ValueError("duplicate tool call ID")
        call_ids.add(call.id)
        calls.append({
            "call_id": call.id,
            "name": call.function.name,
            "arguments": json.loads(call.function.arguments),
        })
    if not text.strip() and not calls:
        raise ValueError("completion has neither text nor tool calls")
    reason = first.get("finish_reason")
    if reason is not None and not isinstance(reason, str):
        raise ValueError("finish_reason must be a string")
    return {"text": text, "tool_calls": calls, "stop_reason": reason}


def _normalize_usage(usage: Any) -> dict[str, Any]:
    """Keep token counts, including known token details, without raw metadata."""
    if not isinstance(usage, dict):
        return {}
    result: dict[str, Any] = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = usage.get(key)
        if type(value) is int and value >= 0:
            result[key] = value
    detail_keys = {
        "prompt_tokens_details": ("cached_tokens", "audio_tokens"),
        "completion_tokens_details": (
            "reasoning_tokens", "audio_tokens",
            "accepted_prediction_tokens", "rejected_prediction_tokens",
        ),
    }
    for key, fields in detail_keys.items():
        details = usage.get(key)
        if isinstance(details, dict):
            result[key] = {
                name: details[name] for name in fields
                if type(details.get(name)) is int and details[name] >= 0
            }
    return result
