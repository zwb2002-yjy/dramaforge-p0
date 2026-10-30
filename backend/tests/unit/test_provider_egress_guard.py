"""Connection-time provider egress guard tests (joint-review P1 SSRF closure).

All DNS resolution and socket creation is faked: these tests are offline,
deterministic, and prove the guard's decisions without any network.
"""

from __future__ import annotations

import asyncio
import ipaddress
import ssl
from typing import Any
from unittest.mock import AsyncMock

import httpcore
import httpx
import pytest
from app.config import Settings
from app.providers.egress import (
    GuardedProviderNetworkBackend,
    ProviderEgressPolicy,
    guarded_provider_transport,
)
from httpcore._backends.base import AsyncNetworkStream


class _FakeStream(AsyncNetworkStream):
    def __init__(self) -> None:
        self.written: list[bytes] = []
        self.tls_hosts: list[str | None] = []
        self.reads = [b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK"]

    def get_extra_info(self, info: str) -> Any:
        return None

    async def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        return self.reads.pop(0) if self.reads else b""

    async def write(self, buffer: bytes, timeout: float | None = None) -> None:
        self.written.append(buffer)

    async def start_tls(
        self,
        ssl_context: ssl.SSLContext,
        server_hostname: str | None = None,
        timeout: float | None = None,
    ) -> AsyncNetworkStream:
        assert ssl_context.check_hostname
        assert ssl_context.verify_mode == ssl.CERT_REQUIRED
        self.tls_hosts.append(server_hostname)
        return self

    async def aclose(self) -> None:
        return None


class _RecordingBackend:
    """Records connect targets; returns a fake stream."""

    def __init__(self) -> None:
        self.targets: list[str] = []
        self.streams: list[_FakeStream] = []

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Any = None,
    ) -> AsyncNetworkStream:
        self.targets.append(host)
        stream = _FakeStream()
        self.streams.append(stream)
        return stream

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Any = None,
    ) -> AsyncNetworkStream:
        raise AssertionError("unix sockets are never used by provider traffic")

    async def sleep(self, seconds: float) -> None:
        return None


def _resolver(*answers: list[str]):
    calls: list[str] = []

    async def resolve(host: str, port: int) -> list[str]:
        calls.append(host)
        return list(answers[len(calls) - 1])

    resolve.calls = calls  # type: ignore[attr-defined]
    return resolve


def _backend(
    policy: ProviderEgressPolicy,
    resolver: Any,
) -> tuple[GuardedProviderNetworkBackend, _RecordingBackend]:
    inner = _RecordingBackend()
    backend = GuardedProviderNetworkBackend(policy=policy, resolver=resolver, inner=inner)  # type: ignore[arg-type]
    return backend, inner


def _public_policy() -> ProviderEgressPolicy:
    return ProviderEgressPolicy()


@pytest.mark.asyncio
async def test_private_resolution_is_blocked_without_opt_in() -> None:
    # The write-time gate passed a hostname; at connect time it resolves to
    # a private address and must fail closed before any socket is opened.
    backend, inner = _backend(_public_policy(), _resolver(["10.0.0.5"]))
    with pytest.raises(httpx.ConnectError, match="PROVIDER_EGRESS_PRIVATE_NOT_AUTHORIZED"):
        await backend.connect_tcp("provider.example.com", 443)
    assert inner.targets == []


@pytest.mark.asyncio
async def test_private_resolution_is_allowed_with_opt_in_and_pinned() -> None:
    policy = ProviderEgressPolicy(allow_private=True)
    backend, inner = _backend(policy, _resolver(["10.0.0.5", "10.0.0.6"]))
    stream = await backend.connect_tcp("provider.example.com", 443)
    assert stream is not None
    # The socket is opened against a validated address, never the hostname.
    assert inner.targets == ["10.0.0.5"]


@pytest.mark.asyncio
async def test_one_bad_resolved_address_fails_the_whole_connection() -> None:
    # Mixed A records: an attacker-controlled second address must not be
    # reachable just because the first one validated.
    backend, inner = _backend(_public_policy(), _resolver(["8.8.8.8", "127.0.0.1"]))
    with pytest.raises(httpx.ConnectError, match="PROVIDER_EGRESS"):
        await backend.connect_tcp("provider.example.com", 443)
    assert inner.targets == []


@pytest.mark.asyncio
async def test_dns_rebinding_on_a_new_connection_is_rejected() -> None:
    # First resolution is public (connects), second resolves private: the
    # new connection must fail closed. Established connections keep their
    # already-validated endpoint for their whole lifetime.
    backend, inner = _backend(_public_policy(), _resolver(["93.184.216.34"], ["10.0.0.5"]))
    await backend.connect_tcp("provider.example.com", 443)
    assert inner.targets == ["93.184.216.34"]
    with pytest.raises(httpx.ConnectError, match="PROVIDER_EGRESS"):
        await backend.connect_tcp("provider.example.com", 443)
    assert inner.targets == ["93.184.216.34"]


async def test_tcp_failover_uses_only_validated_addresses_without_resending_a_request() -> None:
    backend, inner = _backend(_public_policy(), _resolver(["2606:4700::1", "93.184.216.34"]))
    stream = _FakeStream()
    connect = AsyncMock(side_effect=[httpcore.ConnectError("no IPv6 route"), stream])
    inner.connect_tcp = connect
    assert await backend.connect_tcp("provider.example.com", 443, timeout=5) is stream
    assert [call.args[0] for call in connect.await_args_list] == ["2606:4700::1", "93.184.216.34"]
    assert stream.written == []


async def test_dns_resolution_obeys_the_connection_timeout() -> None:
    async def stalled(host: str, port: int) -> list[str]:
        await asyncio.Event().wait()
        return []

    backend, inner = _backend(_public_policy(), stalled)
    with pytest.raises(httpx.ConnectTimeout):
        await asyncio.wait_for(
            backend.connect_tcp("provider.example.com", 443, timeout=0.01), timeout=0.5
        )
    assert inner.targets == []


@pytest.mark.asyncio
async def test_hard_blocked_literals_are_rejected_even_with_private_opt_in() -> None:
    policy = ProviderEgressPolicy(allow_private=True)
    for address in ("169.254.169.254", "240.0.0.1", "100.64.0.5"):
        backend, inner = _backend(policy, _resolver([address]))
        with pytest.raises(httpx.ConnectError, match="PROVIDER_EGRESS_(BLOCKED_TARGET|SHARED)"):
            await backend.connect_tcp(address, 443)
        assert inner.targets == []


@pytest.mark.asyncio
async def test_trusted_network_authorizes_private_and_plain_http_targets() -> None:
    policy = ProviderEgressPolicy(trusted_networks=(ipaddress.ip_network("172.18.6.0/24"),))
    backend, inner = _backend(policy, _resolver(["172.18.6.80"]))
    await backend.connect_tcp("172.18.6.80", 30020)
    assert inner.targets == ["172.18.6.80"]


@pytest.mark.asyncio
async def test_trusted_network_does_not_authorize_hard_blocked_targets() -> None:
    policy = ProviderEgressPolicy(trusted_networks=(ipaddress.ip_network("169.254.0.0/16"),))
    backend, inner = _backend(policy, _resolver(["169.254.169.254"]))
    with pytest.raises(httpx.ConnectError, match="PROVIDER_EGRESS_BLOCKED_TARGET"):
        await backend.connect_tcp("169.254.169.254", 80)
    assert inner.targets == []


@pytest.mark.asyncio
async def test_public_resolution_is_pinned_and_normalized() -> None:
    backend, inner = _backend(_public_policy(), _resolver(["93.184.216.34"]))
    await backend.connect_tcp("Provider.Example.COM.", 443)
    assert inner.targets == ["93.184.216.34"]


@pytest.mark.asyncio
async def test_ip_literal_hosts_skip_resolution() -> None:
    resolver = _resolver(["10.0.0.5"])  # would return private if consulted
    backend, inner = _backend(_public_policy(), resolver)
    stream = await backend.connect_tcp("8.8.8.8", 443)
    assert stream is not None
    assert inner.targets == ["8.8.8.8"]
    assert resolver.calls == []  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_resolver_failure_becomes_connect_error() -> None:
    async def failing(host: str, port: int) -> list[str]:
        raise OSError("name resolution failure")

    backend, inner = _backend(_public_policy(), failing)
    with pytest.raises(httpx.ConnectError, match="PROVIDER_EGRESS_UNRESOLVABLE"):
        await backend.connect_tcp("provider.example.com", 443)
    assert inner.targets == []


async def test_empty_dns_answer_fails_as_a_transport_error() -> None:
    backend, inner = _backend(_public_policy(), _resolver([]))
    with pytest.raises(httpx.ConnectError, match="PROVIDER_EGRESS_UNRESOLVABLE"):
        await backend.connect_tcp("provider.example.com", 443)
    assert inner.targets == []


@pytest.mark.parametrize(
    "url",
    [
        "http://8.8.8.8/v1/models",
        "http://10.0.0.1/v1/models",
        "http://models.internal/v1/models",
        "https://metadata.google.internal/v1/models",
    ],
)
async def test_runtime_url_policy_runs_before_any_pool_access(monkeypatch, url) -> None:
    """Old saved URLs and redirect targets must obey today's scheme policy."""
    from unittest.mock import AsyncMock

    transport = guarded_provider_transport(
        settings=Settings(
            provider_base_url_allow_private=True,
            provider_trusted_http_networks=["172.18.6.0/24"],
        )
    )
    send = AsyncMock(side_effect=AssertionError("untrusted request reached the pool"))
    monkeypatch.setattr(transport._pool, "handle_async_request", send)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(httpx.ConnectError, match="PROVIDER_BASE_URL_"):
            await client.get(url)
    send.assert_not_awaited()


async def test_cancel_uses_guard_and_never_opens_a_private_socket(monkeypatch) -> None:
    from app.providers.egress import GuardedProviderTransport
    from app.providers.openai_compatible_media import OpenAICompatibleMediaRuntime
    from app.providers.runtime import ProviderResumeToken

    settings = Settings(
        openai_compatible_media_enabled=True,
        openai_compatible_media_api_key="synthetic-cancel-fixture",
    )
    resolver = _resolver(["10.0.0.5"])
    connect = AsyncMock(side_effect=AssertionError("private socket must never open"))
    original_send = httpx.AsyncHTTPTransport.handle_async_request

    async def guarded_send(transport, request):
        assert isinstance(transport, GuardedProviderTransport), "cancel bypassed egress guard"
        return await original_send(transport, request)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", guarded_send)
    monkeypatch.setattr("app.providers.egress._resolve_addresses", resolver)
    monkeypatch.setattr("httpcore._backends.auto.AutoBackend.connect_tcp", connect)
    runtime = OpenAICompatibleMediaRuntime(
        settings=settings,
        host="https://provider.example.com",
        transport=guarded_provider_transport(settings=settings),
    )
    with pytest.raises(httpx.ConnectError, match="PROVIDER_EGRESS_PRIVATE_NOT_AUTHORIZED"):
        await runtime.cancel_video(
            ProviderResumeToken(
                provider_type="openai_compatible_media",
                protocol_profile="openai_media_v1",
                remote_task_id="existing-task",
            )
        )
    assert resolver.calls == ["provider.example.com"]
    connect.assert_not_awaited()


@pytest.mark.asyncio
async def test_unix_sockets_are_hard_denied() -> None:
    backend, _inner = _backend(_public_policy(), _resolver([]))
    with pytest.raises(httpx.ConnectError, match="PROVIDER_EGRESS_UNIX_SOCKET_BLOCKED"):
        await backend.connect_unix_socket("/run/provider.sock")


def test_guarded_transport_installs_the_guarded_backend() -> None:
    transport = guarded_provider_transport(settings=Settings(provider_base_url_allow_private=True))
    assert isinstance(transport, httpx.AsyncHTTPTransport)
    pool = transport._pool  # noqa: SLF001 - assertion target
    assert isinstance(pool, httpcore.AsyncConnectionPool)
    assert isinstance(pool._network_backend, GuardedProviderNetworkBackend)  # noqa: SLF001


@pytest.mark.asyncio
async def test_guarded_transports_do_not_share_client_owned_pools() -> None:
    from app.config import Settings

    settings = Settings(
        app_env="test",
        session_secret="egress-test-session-secret-32ch",
        byok_fernet_key="egress-test-byok-fernet-key==",
    )
    first = guarded_provider_transport(settings=settings)
    second = guarded_provider_transport(settings=settings)
    assert first is not second
    assert first._pool is not second._pool
    await first.aclose()
    await second.aclose()


@pytest.mark.parametrize(
    ("url", "address", "tls_host"),
    [
        ("https://provider.example.com/v1/models", "93.184.216.34", "provider.example.com"),
        ("http://172.18.6.80:30020/v1/models", "172.18.6.80", None),
    ],
)
async def test_complete_transport_pins_socket_preserves_host_and_tls(url, address, tls_host):
    settings = Settings(provider_trusted_http_networks=["172.18.6.0/24"])
    backend, inner = _backend(ProviderEgressPolicy.from_settings(settings), _resolver([address]))
    transport = guarded_provider_transport(settings=settings)
    transport._pool._network_backend = backend
    async with httpx.AsyncClient(transport=transport) as client:
        response = await client.get(url, headers={"Authorization": "Bearer synthetic-fixture"})
    assert response.text == "OK"
    assert inner.targets == [address]
    stream = inner.streams[0]
    assert stream.tls_hosts == ([tls_host] if tls_host else [])
    sent = b"".join(stream.written)
    assert f"Host: {httpx.URL(url).netloc.decode()}\r\n".encode() in sent
    assert b"Authorization: Bearer synthetic-fixture\r\n" in sent


@pytest.mark.parametrize(
    ("provider", "profile"),
    [
        ("agnes", "agnes_cn_v1"),
        ("volcengine", "ark_cn_v1"),
        ("minimax", "minimax_cn_v1"),
        ("openai_compatible_media", "openai_media_v1"),
    ],
)
async def test_resolved_media_runtime_blocks_private_dns_before_socket(
    monkeypatch, provider, profile
):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.providers.registry import get_plugin
    from app.providers.runtime import CompiledImageRequest, ProviderRuntimeResolver

    plugin = get_plugin(provider, profile)
    settings = Settings().model_copy(
        update={
            f"{plugin.prefix}_enabled": True,
            f"{plugin.prefix}_api_key": "synthetic-egress-fixture",
        }
    )
    resolver = _resolver(["10.0.0.5"])
    connect = AsyncMock(side_effect=AssertionError("private destination reached socket backend"))
    monkeypatch.setattr("app.providers.egress._resolve_addresses", resolver)
    monkeypatch.setattr("httpcore._backends.auto.AutoBackend.connect_tcp", connect)
    resolved = await ProviderRuntimeResolver(None).resolve(
        plugin=plugin,
        connection=SimpleNamespace(provider_type=provider, base_url="https://provider.example.com"),
        binding=SimpleNamespace(model_id="fixture", invoke_model_value="fixture"),
        entry=SimpleNamespace(contract_manifest_hash="a" * 64),
        settings=settings,
    )
    result = await resolved.runtime.submit_image(
        CompiledImageRequest(
            provider_type=provider,
            protocol_profile=profile,
            model_id="fixture",
            operation="image.generate",
            request_schema_version="1",
            wire_request={"model": "fixture", "prompt": "egress fixture"},
        )
    )
    assert result.status != "succeeded"
    assert resolver.calls == ["provider.example.com"]
    connect.assert_not_awaited()
