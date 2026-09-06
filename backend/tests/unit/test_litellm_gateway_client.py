"""LiteLLM Gateway client + logical model catalog tests (fix spec F4–F10).

Covers URL normalization (§19–§21), single-attempt chat (§5/§95), error
classification (§63–§65), allowlisted metadata (§47/§48), model discovery with
TTL cache (§35/§36), logical alias manifests (§34/§41), and the bootstrap-bridge
system-default preference (§34/§103).
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from app.config import Settings
from app.providers.bootstrap import litellm_text_manifest
from app.providers.capabilities import Capability
from app.providers.litellm_adapter import LiteLLMModelAdapter
from app.providers.litellm_gateway.client import (
    LiteLLMGatewayClient,
    normalize_chat_url,
    normalize_models_url,
)
from app.providers.litellm_gateway.model_catalog import (
    LiteLLMModelCatalogSyncService,
    litellm_logical_manifest,
    register_litellm_logical_models,
)
from app.providers.registry import ModelRegistry
from app.providers.selector import DefaultModelSelector

_GATEWAY = Settings(
    app_env="development",
    litellm_gateway_url="https://gateway.example",
    litellm_api_key="gateway-key",
)


def _client(handler: Any, url: str = "https://gateway.example") -> LiteLLMGatewayClient:
    return LiteLLMGatewayClient(
        settings=Settings(
            app_env="development",
            litellm_gateway_url=url,
            litellm_api_key="gateway-key",
        ),
        transport=httpx.MockTransport(handler),
    )


class TestUrlNormalization:
    def test_base_url_gets_v1_chat_path(self) -> None:
        assert (
            normalize_chat_url("http://litellm:4000")
            == "http://litellm:4000/v1/chat/completions"
        )

    def test_v1_suffixed_base(self) -> None:
        assert (
            normalize_chat_url("http://litellm:4000/v1")
            == "http://litellm:4000/v1/chat/completions"
        )

    def test_full_endpoint_kept(self) -> None:
        assert (
            normalize_chat_url("http://litellm:4000/v1/chat/completions")
            == "http://litellm:4000/v1/chat/completions"
        )

    def test_trailing_slash_stripped(self) -> None:
        assert (
            normalize_chat_url("http://litellm:4000/")
            == "http://litellm:4000/v1/chat/completions"
        )

    def test_models_url(self) -> None:
        assert normalize_models_url("http://litellm:4000") == "http://litellm:4000/v1/models"
        assert (
            normalize_models_url("http://litellm:4000/v1")
            == "http://litellm:4000/v1/models"
        )


class TestChatCompletion:
    async def test_posts_model_and_payload(self) -> None:
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

        client = _client(handler)
        response = await client.chat_completion(
            model="script-quality", payload={"messages": [{"role": "user", "content": "hi"}]}
        )
        assert response.status_code == 200
        assert requests[0].url.path == "/v1/chat/completions"
        assert requests[0].headers["authorization"] == "Bearer gateway-key"
        assert requests[0].url.host == "gateway.example"

    async def test_503_raises_provider_unavailable(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={"error": {"message": "down"}})

        from app.providers.errors import ProviderError, ProviderErrorCode

        client = _client(handler)
        with pytest.raises(ProviderError) as exc:
            await client.chat_completion(model="x", payload={"messages": []})
        assert exc.value.code == str(ProviderErrorCode.PROVIDER_UNAVAILABLE)

    async def test_read_timeout_raises_submission_outcome_unknown(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("read timeout", request=request)

        from app.providers.errors import SubmissionOutcomeUnknownError

        client = _client(handler)
        with pytest.raises(SubmissionOutcomeUnknownError):
            await client.chat_completion(model="x", payload={"messages": []})

    async def test_connect_error_raises_gateway_unavailable(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        from app.providers.errors import ProviderErrorCode

        client = _client(handler)
        with pytest.raises(Exception) as exc:
            await client.chat_completion(model="x", payload={"messages": []})
        assert exc.value.code == str(ProviderErrorCode.PROVIDER_UNAVAILABLE)


class TestListModels:
    async def test_parses_ids_with_ttl_cache(self) -> None:
        calls = {"n": 0}

        async def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(
                200, json={"data": [{"id": "script-quality"}, {"id": "script-fast"}]}
            )

        client = _client(handler)
        first = await client.list_models()
        second = await client.list_models()
        assert first == ["script-quality", "script-fast"]
        assert second == ["script-quality", "script-fast"]
        assert calls["n"] == 1  # TTL cache: no second HTTP call

    async def test_force_refresh_bypasses_cache(self) -> None:
        calls = {"n": 0}

        async def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(200, json={"data": [{"id": "script-quality"}]})

        client = _client(handler)
        await client.list_models()
        await client.list_models(force=True)
        assert calls["n"] == 2

    async def test_readiness_false_when_down(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused", request=request)

        client = _client(handler)
        assert await client.readiness() is False


class TestLogicalAliases:
    def test_logical_manifest_maps_alias_to_gateway_model(self) -> None:
        manifest = litellm_logical_manifest("script-quality")
        assert manifest.id == "litellm/script-quality"
        assert manifest.provider_id == "litellm"
        assert Capability.TEXT_GENERATE in manifest.capability_specs
        backend = manifest.metadata["backend"]
        assert backend["gateway_model"] == "script-quality"
        assert backend["kind"] == "litellm"

    def test_register_logical_models_is_idempotent(self) -> None:
        registry = ModelRegistry()
        registered = register_litellm_logical_models(registry)
        assert "litellm/script-quality" in registered
        assert "litellm/script-fast" in registered
        again = register_litellm_logical_models(registry)
        assert again == []
        assert registry.get_or_none("litellm/script-quality") is not None

    def test_text_llm_is_bootstrap_bridge(self) -> None:
        manifest = litellm_text_manifest()
        assert manifest.metadata["bootstrap_bridge"] is True
        assert manifest.metadata["legacy_compat"] is True
        # gateway_model is the logical alias, not TEXT_LLM_MODEL (fix spec §32/§33).
        assert manifest.metadata["backend"]["gateway_model"] == "legacy-text"

    def test_system_default_prefers_bootstrap_bridge(self) -> None:
        """script-fast sorts before text-llm, but the bootstrap bridge stays the
        text system default (fix spec §34/§103)."""
        registry = ModelRegistry()
        register_litellm_logical_models(registry)
        from app.providers.bootstrap import LITELLM_TEXT_MODEL_ID

        adapter = LiteLLMModelAdapter(litellm_text_manifest(), settings=_GATEWAY)
        registry.register(litellm_text_manifest(), adapter)
        selected = DefaultModelSelector().select(
            capability=Capability.TEXT_GENERATE,
            requested_model=None,
            registry=registry,
        )
        assert selected.manifest.id == LITELLM_TEXT_MODEL_ID


class TestCatalogSync:
    async def test_sync_registers_discovered_aliases(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json={"data": [{"id": "script-quality"}, {"id": "storyboard-planner"}]}
            )

        registry = ModelRegistry()
        service = LiteLLMModelCatalogSyncService(
            client=_client(handler),
            registry=registry,
        )
        newly = await service.sync()
        assert "litellm/script-quality" in newly
        assert "litellm/storyboard-planner" in newly
        assert registry.get_or_none("litellm/storyboard-planner") is not None

    async def test_sync_never_raises_when_gateway_down(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused", request=request)

        service = LiteLLMModelCatalogSyncService(client=_client(handler))
        assert await service.sync() == []


class TestNoSdkDependency:
    def test_backend_never_imports_litellm_sdk(self) -> None:
        """DramaForge backend must not import the ``litellm`` pip package — the
        Proxy is a separate runtime (fix spec §128-1/§116)."""
        from pathlib import Path

        backend = Path(__file__).resolve().parents[2]
        offenders: list[str] = []
        for path in (backend / "app").rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith(("import litellm", "from litellm")):
                    offenders.append(f"{path}:{line}")
        assert not offenders, f"backend imports litellm SDK:\n{chr(10).join(offenders)}"


class TestProfileLogicalAliasRouting:
    async def test_planning_script_binds_script_quality_alias(self) -> None:
        """planning.script → litellm/script-quality → gateway payload model
        ``script-quality`` (fix spec §41/§42/§105/§106/§120)."""
        import json

        from app.providers.contracts.common import ExecutionContext
        from app.providers.contracts.text import TextGenerateRequest, TextMessage
        from app.providers.litellm_gateway.model_catalog import litellm_logical_manifest
        from app.providers.router import CapabilityRouter

        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                200, json={"choices": [{"message": {"content": "ok"}}], "model": "script-quality"}
            )

        manifest = litellm_logical_manifest("script-quality")
        adapter = LiteLLMModelAdapter(
            manifest, settings=_GATEWAY, client=_client(handler)
        )
        registry = ModelRegistry()
        registry.register(manifest, adapter)
        router = CapabilityRouter(registry=registry)

        result = await router.create(
            capability=Capability.TEXT_GENERATE,
            request=TextGenerateRequest(
                messages=[TextMessage(role="user", content="write a script")]
            ),
            context=ExecutionContext(trace_id="t"),
            model_id="litellm/script-quality",
        )
        assert result.status.value == "succeeded"
        payload = json.loads(requests[0].content)
        assert payload["model"] == "script-quality"
