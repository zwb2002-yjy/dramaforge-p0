"""Prometheus metrics for API, outbox, and SSE recovery."""

from prometheus_client import Counter, Gauge, generate_latest

REQUESTS_TOTAL = Counter(
    "dramaforge_http_requests_total",
    "Total HTTP requests handled by the API",
    ["method", "path", "status"],
)

OUTBOX_PENDING = Gauge(
    "dramaforge_outbox_pending",
    "Number of outbox events in pending status",
)

OUTBOX_OLDEST_WAIT_SECONDS = Gauge(
    "dramaforge_outbox_oldest_wait_seconds",
    "Age in seconds of the oldest pending outbox event",
)

OUTBOX_PUBLISHED_TOTAL = Counter(
    "dramaforge_outbox_published_total",
    "Outbox events successfully published",
)

OUTBOX_DEAD_LETTER_TOTAL = Counter(
    "dramaforge_outbox_dead_letter_total",
    "Outbox events moved to dead letter",
)

OUTBOX_REPLAY_TOTAL = Counter(
    "dramaforge_outbox_replay_total",
    "Human dead-letter replay attempts",
    ["result"],
)

SSE_RECONNECT_TOTAL = Counter(
    "dramaforge_sse_reconnect_total",
    "SSE clients resuming via Last-Event-ID",
)


def metrics_payload() -> bytes:
    return generate_latest()
