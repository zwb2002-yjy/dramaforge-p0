"""New text execution uses immutable owned Proxy references; retries prove the send boundary."""

from __future__ import annotations

import json
from uuid import uuid4

import httpx
import pytest
from app.providers.bootstrap import default_v3_registry
from app.providers.capabilities import Capability
from app.providers.contracts.common import ExecutionContext
from app.providers.contracts.text import TextGenerateRequest, TextMessage
from app.providers.errors import ProviderError, SubmissionOutcomeUnknownError
from app.providers.litellm_gateway.client import LiteLLMGatewayClient
from app.providers.litellm_gateway.management import GatewayReference
from app.providers.litellm_gateway.workspace_registry import workspace_model_registry
from app.providers.registry import ModelRegistry
from app.providers.selector import DefaultModelSelector
from app.providers.workspace_credentials import (
    WorkspaceCredentialConfigurationError,
    runtime_text_gateway_settings,
)
from test_gateway_model_management import fixture, model
from test_gateway_model_management import session as session


async def test_managed_selection_has_no_discovery_or_external_transport(session, monkeypatch):
    actor, workspace, cfg, remote, manager = await fixture(session)
    connection = await manager.register(workspace_id=workspace.id, actor=actor, body=model())
    monkeypatch.setattr("app.providers.workspace_credentials.get_settings", lambda: cfg)
    registry = await workspace_model_registry(
        session, workspace_id=workspace.id, base_registry=default_v3_registry()[0]
    )
    text = registry.find_by_capability(Capability.TEXT_GENERATE)
    assert len(text) == 1
    selected = DefaultModelSelector().select(
        capability=Capability.TEXT_GENERATE, requested_model=None, registry=registry
    )
    reference = GatewayReference.model_validate(connection.gateway_ref)
    assert selected.manifest.metadata["gateway_reference"] == reference.execution_reference()
    sent = []

    async def send(request):
        sent.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    selected.adapter._client_override = LiteLLMGatewayClient(
        settings=cfg, transport=httpx.MockTransport(send)
    )
    result = await selected.adapter.create(
        Capability.TEXT_GENERATE,
        TextGenerateRequest(messages=[TextMessage(role="user", content="synthetic")]),
        ExecutionContext(trace_id="frozen"),
    )
    assert result.status.value == "succeeded" and len(sent) == 1
    assert str(sent[0].url) == cfg.litellm_gateway_url + "/v1/chat/completions"
    assert (
        json.loads(sent[0].content)["metadata"]["dramaforge_execution"]
        == reference.execution_reference()
    )
    assert remote.creates == 1
    other = await workspace_model_registry(
        session, workspace_id=uuid4(), base_registry=ModelRegistry()
    )
    assert not other.find_by_capability(Capability.TEXT_GENERATE)
    for native in ({"metadata": {}}, {"api_base": "https://external.example"}, {"stream": True}):
        with pytest.raises(ProviderError):
            await selected.adapter.create(
                Capability.TEXT_GENERATE,
                TextGenerateRequest(
                    messages=[TextMessage(role="user", content="synthetic")], native_options=native
                ),
                ExecutionContext(trace_id="reject"),
            )
    assert len(sent) == 1
    connection.base_url = "https://external.example/v1"
    with pytest.raises(WorkspaceCredentialConfigurationError):
        await runtime_text_gateway_settings(session, connection=connection, settings=cfg)


@pytest.mark.parametrize("kind", [httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout])
@pytest.mark.parametrize("recover", [True, False])
async def test_only_df_to_proxy_proven_presend_failure_has_one_bounded_retry(kind, recover):
    from app.config import Settings

    attempts = 0
    upstream = 0

    async def send(request):
        nonlocal attempts, upstream
        attempts += 1
        if attempts == 1 or not recover:
            raise kind("synthetic pre-send", request=request)
        upstream += 1
        return httpx.Response(200, json={"choices": []})

    client = LiteLLMGatewayClient(
        settings=Settings(
            _env_file=None, litellm_gateway_url="http://proxy.internal", litellm_api_key="synthetic"
        ),
        transport=httpx.MockTransport(send),
    )
    if recover:
        response = await client.chat_completion(model="fixed", payload={"messages": []})
        assert response.metadata["df_proxy_transport_attempts"] == 2
    else:
        with pytest.raises(ProviderError) as error:
            await client.chat_completion(model="fixed", payload={"messages": []})
        assert error.value.details["df_proxy_transport_attempts"] == 2
        assert error.value.details["df_proxy_failure_phase"] == "df_proxy_pre_send"
    assert attempts == 2 and upstream == int(recover)


@pytest.mark.parametrize(
    "outcome", [429, 503, 408, httpx.ReadTimeout, httpx.WriteError, httpx.RemoteProtocolError]
)
async def test_proxy_response_and_possible_send_are_never_presend_evidence(outcome):
    from app.config import Settings

    calls = 0

    async def send(request):
        nonlocal calls
        calls += 1
        if isinstance(outcome, int):
            return httpx.Response(outcome, json={"error": {"message": "synthetic"}})
        raise outcome("synthetic after possible send", request=request)

    client = LiteLLMGatewayClient(
        settings=Settings(
            _env_file=None, litellm_gateway_url="http://proxy.internal", litellm_api_key="synthetic"
        ),
        transport=httpx.MockTransport(send),
    )
    with pytest.raises(ProviderError) as error:
        await client.chat_completion(model="fixed", payload={"messages": []})
    if outcome in (408, httpx.ReadTimeout, httpx.WriteError, httpx.RemoteProtocolError):
        assert isinstance(error.value, SubmissionOutcomeUnknownError)
    assert error.value.details["df_proxy_transport_attempts"] == 1
    assert error.value.details["df_proxy_failure_phase"] == (
        "proxy_response" if isinstance(outcome, int) else "df_proxy_possible_send"
    )
    assert calls == 1
