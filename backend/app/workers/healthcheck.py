"""Read-only Director queue liveness without importing its jobs or application settings.

Arq's default heartbeat expires after its 3600s interval plus 1s. Inspect that
expiry, not the human-readable timestamp (which has no year/timezone). This is
queue-level liveness with Arq's existing stale window, not per-process readiness.
"""

from __future__ import annotations

import os
import signal
import sys
from types import FrameType

MAX_HEARTBEAT_TTL_MS = 3_601_000
PROBE_TIMEOUT_SECONDS = 3.0


def heartbeat_is_healthy(redis_url: str, queue_name: str) -> bool:
    # Lazy imports keep even dependency loading inside the CLI's wall-clock deadline.
    from redis import Redis
    from redis.backoff import NoBackoff
    from redis.retry import Retry

    key = queue_name + ":health-check"
    with Redis.from_url(
        redis_url,
        socket_connect_timeout=1,
        socket_timeout=1,
        retry_on_timeout=False,
        retry=Retry(NoBackoff(), 0),
    ) as client:
        # No PING, writes, Lua or transaction: only the configured queue's sentinel.
        with client.pipeline(transaction=False) as pipe:
            pipe.get(key)
            pipe.pttl(key)
            heartbeat, ttl_ms = pipe.execute()
        healthy = bool(heartbeat) and 0 < ttl_ms <= MAX_HEARTBEAT_TTL_MS
    return healthy


def _deadline_expired(signum: int, frame: FrameType | None) -> None:
    raise TimeoutError("worker health deadline exceeded")


def main() -> int:
    redis_url = os.environ.get("REDIS_URL", "")
    # Match director.py's fallback without importing WorkerSettings or loading .env.
    queue_name = os.environ.get("DIRECTOR_QUEUE_NAME", "arq:director")
    if not redis_url.strip() or not queue_name.strip():
        print("Health check failed: empty Redis URL or Director queue", file=sys.stderr)
        return 1

    # Runtime containers are Linux. Bound DNS/import/connect/read/close together;
    # socket timeouts alone do not cover DNS or dependency/connection teardown.
    previous_handler = signal.signal(signal.SIGALRM, _deadline_expired)
    signal.setitimer(signal.ITIMER_REAL, PROBE_TIMEOUT_SECONDS)
    try:
        healthy = heartbeat_is_healthy(redis_url, queue_name)
    except Exception as exc:
        # Do not print exception messages: Redis URLs may contain credentials.
        print(f"Health check failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)

    if not healthy:
        print("Health check failed: missing or expired queue heartbeat", file=sys.stderr)
        return 1
    # Only report success after both the read and connection cleanup complete.
    print("Health check successful: queue heartbeat has a valid expiry")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
