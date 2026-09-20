"""Resident transactional-Outbox dispatcher for the Compose runtime."""

from __future__ import annotations

import asyncio
import logging
import os
import socket

from app.runtime.provider_recovery import recover_interrupted_provider_jobs
from app.runtime.scheduler import NodeRunScheduler, RedisStreamPublisher
from app.shared.db import get_session_factory
from app.shared.model_registry import load_all_models

logger = logging.getLogger(__name__)
POLL_SECONDS = float(os.getenv("OUTBOX_DISPATCH_INTERVAL_SECONDS", "1"))
PROVIDER_RECOVERY_POLL_SECONDS = 60.0

# This resident process writes OutboxEvent rows directly. Register every ORM
# model before SQLAlchemy compiles the cross-domain foreign keys during flush.
load_all_models()


async def dispatch_once(*, worker_id: str) -> int:
    """Publish pending Outbox events and enqueue durable NodeRuns once."""
    from app.config import get_settings

    factory = get_session_factory()
    async with factory() as session:
        publisher = RedisStreamPublisher(get_settings().redis_url)
        try:
            return await NodeRunScheduler(session, publisher=publisher).dispatch_pending(
                worker_id=worker_id
            )
        finally:
            await publisher.close()


async def _dispatch_forever(*, worker_id: str) -> None:
    """Keep dispatching after temporary infrastructure failures."""
    while True:
        try:
            dispatched = await dispatch_once(worker_id=worker_id)
            if dispatched:
                logger.info("outbox_dispatcher dispatched=%s", dispatched)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("outbox_dispatcher iteration failed")
        await asyncio.sleep(POLL_SECONDS)


async def _recover_providers_forever() -> None:
    """Scan independently of both media capacity and a blocked Outbox iteration."""
    state: dict[str, object] = {}
    loop = asyncio.get_running_loop()
    while True:
        tick_started = loop.time()
        try:
            counts = await recover_interrupted_provider_jobs(state)
            if any(counts.values()):
                logger.info("provider_recovery %s", counts)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - infrastructure failure must not stop later ticks
            logger.exception("provider_recovery iteration failed")
        await asyncio.sleep(max(0, PROVIDER_RECOVERY_POLL_SECONDS - (loop.time() - tick_started)))


async def run_forever() -> None:
    """Own both bounded scheduling loops in the existing resident dispatcher."""
    worker_id = f"outbox-dispatcher:{socket.gethostname()}"
    async with asyncio.TaskGroup() as tasks:
        tasks.create_task(_dispatch_forever(worker_id=worker_id), name="outbox-dispatch")
        tasks.create_task(_recover_providers_forever(), name="provider-recovery")


def main() -> int:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    asyncio.run(run_forever())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
