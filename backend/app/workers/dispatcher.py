"""Resident transactional-Outbox dispatcher for the Compose runtime."""

from __future__ import annotations

import asyncio
import logging
import os
import socket

from app.runtime.scheduler import NodeRunScheduler, RedisStreamPublisher
from app.shared.db import get_session_factory
from app.shared.model_registry import load_all_models

logger = logging.getLogger(__name__)
POLL_SECONDS = float(os.getenv("OUTBOX_DISPATCH_INTERVAL_SECONDS", "1"))

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


async def run_forever() -> None:
    """Keep dispatching after temporary infrastructure failures."""
    worker_id = f"outbox-dispatcher:{socket.gethostname()}"
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


def main() -> int:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    asyncio.run(run_forever())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
