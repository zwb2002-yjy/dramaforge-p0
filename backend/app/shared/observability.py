"""Minimal Prometheus metrics registration for BOOT-0."""

from prometheus_client import Counter, generate_latest

REQUESTS_TOTAL = Counter(
    "dramaforge_http_requests_total",
    "Total HTTP requests handled by the API",
    ["method", "path", "status"],
)


def metrics_payload() -> bytes:
    return generate_latest()
