"""Close event-loop-owned runtime clients at API/worker shutdown."""

from app.providers.http_client import close_provider_http_pools
from app.runtime.queue_pool import close_queue_pools


async def close_runtime_resources() -> None:
    try:
        await close_provider_http_pools()
    finally:
        await close_queue_pools()


async def shutdown_runtime_resources(ctx: dict[str, object]) -> None:
    await close_runtime_resources()
