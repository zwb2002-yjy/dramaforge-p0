import asyncio

import pytest
from app.config import Settings
from app.providers.http_client import close_provider_http_pools, provider_http_client


async def test_request_clients_reuse_socket_without_sharing_cookies_or_env_proxy(monkeypatch):
    accepts = 0
    requests = []

    async def handle(reader, writer):
        nonlocal accepts
        accepts += 1
        try:
            while True:
                data = await reader.readuntil(b"\r\n\r\n")
                requests.append(data)
                writer.write(
                    b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nSet-Cookie: secret=private\r\n\r\nOK"
                )
                await writer.drain()
        except asyncio.IncompleteReadError:
            pass
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    cfg = Settings(app_env="test", provider_trusted_http_networks=["127.0.0.0/8"])
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "")
    try:
        for _ in range(3):
            async with provider_http_client(timeout=2, settings=cfg) as client:
                assert (await client.get(f"http://127.0.0.1:{port}/")).text == "OK"
        assert accepts == 1
        assert len(requests) == 3
        assert all(b"cookie:" not in request.lower() for request in requests)
    finally:
        await close_provider_http_pools()
        server.close()
        await server.wait_closed()


async def test_default_provider_client_blocks_private_destination():
    import httpx

    try:
        async with provider_http_client(timeout=1, settings=Settings(app_env="test")) as client:
            with pytest.raises(httpx.ConnectError):
                await client.get("http://169.254.169.254/latest/meta-data")
    finally:
        await close_provider_http_pools()


async def test_default_transport_factory_is_called_only_once_per_policy(monkeypatch):
    import app.providers.http_client as module

    await close_provider_http_pools()
    original_factory = module.guarded_provider_transport
    creations = 0

    def counting_factory(*, settings):
        nonlocal creations
        creations += 1
        return original_factory(settings=settings)

    monkeypatch.setattr(module, "guarded_provider_transport", counting_factory)
    cfg = Settings(app_env="test", provider_trusted_http_networks=["127.0.0.0/8"])
    try:
        for _ in range(5):
            async with provider_http_client(timeout=1, settings=cfg):
                pass
        assert creations == 1
    finally:
        await close_provider_http_pools()
