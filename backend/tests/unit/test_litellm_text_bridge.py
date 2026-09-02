"""LiteLLM text bridge tests (spec §113/§114, M7/M8).

Covers the Generic LiteLLM adapter wire contract, the router path, and the
the canonical LiteLLM capability and resolver path.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any
from uuid import uuid4

import httpx
import pytest
from app.config import Settings
from app.providers.bootstrap import litellm_text_manifest
from app.providers.capabilities import Capability
from app.providers.contracts.common import (
    ExecutionContext,
    GenerationStatus,
)
from app.providers.contracts.text import TextGenerateRequest, TextMessage
from app.providers.litellm_adapter import LiteLLMModelAdapter
from app.providers.model_profiles.resolver import ModelBindingResolver
from app.providers.model_profiles.slots import ModelSlot
from app.providers.registry import ModelRegistry
from app.providers.router import CapabilityRouter
from app.shared.base import Base
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_GATEWAY = Settings(
    app_env="development",
    litellm_gateway_url="https://gateway.example",
    litellm_api_key="gateway-key",
)


def _gateway_settings() -> Settings:
    return Settings(
        app_env="development",
        litellm_gateway_url="https://gateway.example",
        litellm_api_key="gateway-key",
    )


def _text_result(payload: dict[str, Any]) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": "generated text"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            "model": "deepseek-v4-flash",
        },
        request=payload and httpx.Request("POST", "https://gateway.example/v1/chat/completions"),
    )


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as s:
        yield s
    await engine.dispose()


async def test_litellm_adapter_builds_chat_contract() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "hello from gateway"}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 3},
            },
        )

    manifest = litellm_text_manifest()
    adapter = LiteLLMModelAdapter(
        manifest,
        settings=_gateway_settings(),
        transport=httpx.MockTransport(handler),
    )
    result = await adapter.create(
        Capability.TEXT_GENERATE,
        TextGenerateRequest(
            messages=[TextMessage(role="user", content="hi")],
            max_tokens=24,
        ),
        ExecutionContext(trace_id="t"),
    )
    assert result.status == GenerationStatus.SUCCEEDED
    assert result.provider_metadata["text"] == "hello from gateway"
    assert len(requests) == 1
    assert requests[0].url.path == "/v1/chat/completions"
    payload = json.loads(requests[0].content)
    backend = manifest.metadata["backend"]
    assert payload["model"] == backend["gateway_model"]
    assert payload["messages"] == [{"role": "user", "content": "hi"}]
    assert payload["max_tokens"] == 24


async def test_litellm_adapter_unconfigured_fails_closed() -> None:
    manifest = litellm_text_manifest()
    adapter = LiteLLMModelAdapter(
        manifest,
        settings=Settings(app_env="development"),
    )
    assert adapter.configured() is False
    from app.providers.model_profiles.errors import MODEL_PROFILE_MODEL_NOT_CONFIGURED

    with pytest.raises(Exception) as exc_info:
        await adapter.create(
            Capability.TEXT_GENERATE,
            TextGenerateRequest(messages=[TextMessage(role="user", content="hi")]),
            ExecutionContext(trace_id="t"),
        )
    assert exc_info.value.details["code"] == MODEL_PROFILE_MODEL_NOT_CONFIGURED


async def test_litellm_adapter_single_attempt_on_gateway_503() -> None:
    """DramaForge does ONE POST — LiteLLM Router owns retry (fix spec §5/§95)."""
    calls = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503, json={"error": {"message": "upstream down"}})

    manifest = litellm_text_manifest()
    adapter = LiteLLMModelAdapter(
        manifest,
        settings=_gateway_settings(),
        transport=httpx.MockTransport(handler),
    )
    result = await adapter.create(
        Capability.TEXT_GENERATE,
        TextGenerateRequest(prompt="hi"),
        ExecutionContext(trace_id="t"),
    )
    assert result.status == GenerationStatus.FAILED
    assert calls["n"] == 1
    assert result.provider_metadata["error_code"] == "provider_unavailable"


async def test_litellm_adapter_classifies_gateway_errors() -> None:
    """401→auth, unknown-model-400→model_unavailable, 429→rate_limited
    (fix spec §63/§98)."""
    cases = [
        (401, {"error": {"message": "Unauthorized"}}, "auth_failed"),
        (
            400,
            {"error": {"message": "Invalid model name passed in model=nope"}},
            "model_unavailable",
        ),
        (429, {"error": {"message": "rate limit"}}, "rate_limited"),
    ]

    for status, body, expected_code in cases:
        async def handler(
            request: httpx.Request, status=status, body=body
        ) -> httpx.Response:
            return httpx.Response(status, json=body)

        manifest = litellm_text_manifest()
        adapter = LiteLLMModelAdapter(
            manifest,
            settings=_gateway_settings(),
            transport=httpx.MockTransport(handler),
        )
        result = await adapter.create(
            Capability.TEXT_GENERATE,
            TextGenerateRequest(prompt="hi"),
            ExecutionContext(trace_id="t"),
        )
        assert result.status == GenerationStatus.FAILED, status
        assert result.provider_metadata["error_code"] == expected_code, status


async def test_litellm_adapter_read_timeout_returns_submit_unknown() -> None:
    """Read timeout after POST is SUBMISSION_AMBIGUOUS — may be billed, never
    auto re-POST (fix spec §64/§65)."""
    calls = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ReadTimeout("timed out reading response", request=request)

    manifest = litellm_text_manifest()
    adapter = LiteLLMModelAdapter(
        manifest,
        settings=_gateway_settings(),
        transport=httpx.MockTransport(handler),
    )
    result = await adapter.create(
        Capability.TEXT_GENERATE,
        TextGenerateRequest(prompt="hi"),
        ExecutionContext(trace_id="t"),
    )
    assert result.status == GenerationStatus.SUBMIT_UNKNOWN
    assert result.provider_metadata["error_code"] == "submission_outcome_unknown"
    assert calls["n"] == 1


async def test_litellm_adapter_records_allowlisted_metadata() -> None:
    """x-litellm-* cost/retry/fallback/latency headers land in provider_metadata;
    secrets never do (fix spec §47/§48/§100/§121)."""
    requests_seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests_seen.append(request)
        return httpx.Response(
            200,
            headers={
                "x-litellm-response-cost": "0.00123",
                "x-litellm-attempted-retries": "1",
                "x-litellm-attempted-fallbacks": "0",
                "x-litellm-response-duration-ms": "42.5",
                "x-litellm-call-id": "req-123",
                "x-litellm-model-name": "openai/script-quality-deployment",
            },
            json={
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 2},
                "model": "script-quality",
            },
        )

    manifest = litellm_text_manifest()
    adapter = LiteLLMModelAdapter(
        manifest,
        settings=_gateway_settings(),
        transport=httpx.MockTransport(handler),
    )
    result = await adapter.create(
        Capability.TEXT_GENERATE,
        TextGenerateRequest(prompt="hi"),
        ExecutionContext(trace_id="t"),
    )
    assert result.status == GenerationStatus.SUCCEEDED
    md = result.provider_metadata
    assert str(md["litellm_response_cost"]) == "0.00123"
    assert md["litellm_attempted_retries"] == 1
    assert md["litellm_attempted_fallbacks"] == 0
    assert md["litellm_response_duration_ms"] == 42.5
    assert md["request_id"] == "req-123"
    # Authorization is never reflected into metadata.
    assert "authorization" not in {str(k).lower() for k in md}
    assert md["usage"] == {"prompt_tokens": 5, "completion_tokens": 2}


async def test_router_routes_text_generate_through_litellm_model() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "router text"}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 2},
            },
        )

    manifest = litellm_text_manifest()
    adapter = LiteLLMModelAdapter(
        manifest,
        settings=_gateway_settings(),
        transport=httpx.MockTransport(handler),
    )
    registry = ModelRegistry()
    registry.register(manifest, adapter)
    router = CapabilityRouter(registry=registry)
    result = await router.create(
        capability=Capability.TEXT_GENERATE,
        request=TextGenerateRequest(
            messages=[TextMessage(role="user", content="make a brief")],
            max_tokens=100,
        ),
        context=ExecutionContext(trace_id="t"),
        model_id=manifest.id,
    )
    assert result.status == GenerationStatus.SUCCEEDED
    assert result.provider_metadata["text"] == "router text"


async def test_resolver_returns_system_text_model(
    session: AsyncSession,
) -> None:
    """The default registry's system default for text.generate is the LiteLLM
    text model (spec §15 system-default tier)."""
    resolver = ModelBindingResolver(session)
    resolved = await resolver.resolve(
        workspace_id=uuid4(),
        project_id=None,
        slot=ModelSlot.PLANNING_SCRIPT,
        capability=Capability.TEXT_GENERATE,
    )
    assert resolved.source == "system_default"
    assert resolved.model_id == "litellm/text-llm"
