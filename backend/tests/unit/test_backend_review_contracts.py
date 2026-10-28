"""Executable boundaries retained from the backend review."""

import ast
import re
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from app.runtime.scheduler import RedisStreamPublisher

ROOT = Path(__file__).resolve().parents[3]


async def test_slow_film_cleanup_cannot_stall_periodic_provider_recovery(monkeypatch):
    import asyncio

    from app.workers import dispatcher

    calls = 0

    async def recover(_state):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise asyncio.CancelledError
        return {}

    async def blocked_cleanup():
        await asyncio.Event().wait()

    monkeypatch.setattr(dispatcher, "recover_interrupted_provider_jobs", recover)
    monkeypatch.setattr(dispatcher, "FINAL_FILM_CLEANUP_TIMEOUT_SECONDS", 0.01, raising=False)
    monkeypatch.setattr(dispatcher, "PROVIDER_RECOVERY_POLL_SECONDS", 0.01)
    monkeypatch.setattr(
        "app.production.final_film_uploads.sweep_final_film_uploads", blocked_cleanup
    )
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(dispatcher._recover_providers_forever(), timeout=1)
    assert calls == 2


def test_documented_alembic_head_matches_single_current_head():
    config = Config()
    config.set_main_option("script_location", str(ROOT / "backend/alembic"))
    heads = ScriptDirectory.from_config(config).get_heads()
    documented = re.search(r"^Alembic head: (\w+)", (ROOT / "docs/DATA_MODEL.md").read_text(), re.M)
    assert documented is not None
    assert heads == [documented[1]]


def test_provider_http_clients_use_the_guarded_entrypoint():
    # The fixed internal LiteLLM hop has a separate operator trust boundary.
    allowed = {"http_client.py", "litellm_gateway/client.py", "litellm_gateway/management.py"}
    providers = ROOT / "backend/app/providers"
    for path in providers.rglob("*.py"):
        if path.relative_to(providers).as_posix() in allowed:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assert not any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "httpx"
            and node.func.attr == "AsyncClient"
            for node in ast.walk(tree)
        ), f"provider client bypasses shared egress guard: {path}"


async def test_redis_stream_publication_is_bounded_without_process_memory_mirror():
    publisher = RedisStreamPublisher("redis://unused")
    redis = AsyncMock()
    redis.xadd.return_value = "1-0"
    publisher._redis = redis
    assert await publisher.publish("production.facts.v1", {"payload": {}}) == "1-0"
    assert redis.xadd.call_args.kwargs == {"maxlen": 10000, "approximate": True}
    assert publisher.messages == []


async def test_queue_pool_is_shared_across_concurrent_enqueue_calls_and_closed(monkeypatch):
    import asyncio

    from app.runtime.queue_pool import close_queue_pools, queue_pool

    pool = AsyncMock()
    connect = AsyncMock(return_value=pool)
    monkeypatch.setattr("arq.create_pool", connect)
    try:
        assert (
            await asyncio.gather(*(queue_pool("redis://pool-test") for _ in range(5))) == [pool] * 5
        )
        connect.assert_awaited_once()
        pool.close.assert_not_awaited()
    finally:
        await close_queue_pools()
    pool.close.assert_awaited_once()


def test_authentication_gateway_rate_limit_is_explicit():
    nginx = (ROOT / "frontend/nginx.conf").read_text()
    assert "limit_req_zone $binary_remote_addr zone=auth_requests:10m rate=5r/m;" in nginx
    assert "location ~ ^/api/v1/auth/(login|register)$" in nginx
    assert "limit_req zone=auth_requests burst=5 nodelay;" in nginx
    assert "limit_req_status 429;" in nginx
