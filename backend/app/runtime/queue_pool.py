"""One owned Arq pool per Redis URL and event loop."""

from __future__ import annotations

import asyncio
from weakref import WeakKeyDictionary

from arq.connections import ArqRedis

_pools: WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, asyncio.Task[ArqRedis]]] = (
    WeakKeyDictionary()
)


async def queue_pool(redis_url: str) -> ArqRedis:
    from arq import create_pool
    from arq.connections import RedisSettings

    async def connect() -> ArqRedis:
        settings = RedisSettings.from_dsn(redis_url)
        settings.conn_timeout = 1
        settings.conn_retries = 0
        settings.conn_retry_delay = 0
        return await create_pool(settings)

    pools = _pools.setdefault(asyncio.get_running_loop(), {})
    if redis_url not in pools:
        pools[redis_url] = asyncio.create_task(connect())
    task = pools[redis_url]
    try:
        return await asyncio.shield(task)
    except Exception:
        if pools.get(redis_url) is task:
            del pools[redis_url]
        raise


async def close_queue_pools() -> None:
    pools = _pools.pop(asyncio.get_running_loop(), {})
    for task in pools.values():
        try:
            pool = await task
        except Exception:
            continue
        await pool.close()
