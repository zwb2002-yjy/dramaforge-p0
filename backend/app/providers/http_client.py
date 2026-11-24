"""Guarded process/loop-owned pools with request-local clients and cookies."""

from __future__ import annotations

import asyncio
from weakref import WeakKeyDictionary

import httpx

from app.config import Settings, get_settings
from app.providers.egress import GuardedProviderTransport, guarded_provider_transport

_pools: WeakKeyDictionary[
    asyncio.AbstractEventLoop, dict[tuple[object, ...], httpx.AsyncBaseTransport]
] = WeakKeyDictionary()


class _BorrowedTransport(httpx.AsyncBaseTransport):
    def __init__(self, inner: httpx.AsyncBaseTransport) -> None:
        self._inner = inner

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        # Request-local AsyncClient must not close the process-owned pool.
        pass


def provider_http_client(
    *,
    timeout: float | httpx.Timeout,
    transport: httpx.AsyncBaseTransport | None = None,
    settings: Settings | None = None,
) -> httpx.AsyncClient:
    """Every default provider connection is guarded, including poll/cancel.

    Explicit test transports remain caller-owned by their request client. Live
    guarded transports share only sockets; credentials, headers and cookies are
    never stored on the shared object. Environment proxies are always disabled.
    """
    if transport is None:
        # Resolve the pool key before constructing a transport. The common
        # request path must not allocate and discard an unused HTTP pool.
        cfg = settings or get_settings()
        key = (cfg.provider_base_url_allow_private, tuple(cfg.provider_trusted_http_networks))
        pools = _pools.setdefault(asyncio.get_running_loop(), {})
        if key not in pools:
            pools[key] = guarded_provider_transport(settings=cfg)
        transport = _BorrowedTransport(pools[key])
    elif isinstance(transport, GuardedProviderTransport):
        cfg = transport.settings
        key = (cfg.provider_base_url_allow_private, tuple(cfg.provider_trusted_http_networks))
        pools = _pools.setdefault(asyncio.get_running_loop(), {})
        if key not in pools:
            pools[key] = transport
        transport = _BorrowedTransport(pools[key])
    return httpx.AsyncClient(
        timeout=timeout,
        transport=transport,
        trust_env=False,
        follow_redirects=False,
    )


async def close_provider_http_pools() -> None:
    pools = _pools.pop(asyncio.get_running_loop(), {})
    for transport in pools.values():
        await transport.aclose()
