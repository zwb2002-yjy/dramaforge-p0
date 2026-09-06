"""Shared PostgreSQL reachability helpers for host and container test runs."""

from __future__ import annotations

import os
import socket
from urllib.parse import urlsplit

from sqlalchemy import create_engine, text


def sync_url(url: str) -> str:
    """Use psycopg for synchronous probes regardless of the async driver."""
    return url.replace("postgresql+asyncpg://", "postgresql+psycopg://").replace(
        "postgresql+psycopg2://", "postgresql+psycopg://"
    )


def target(url: str) -> tuple[str, int]:
    parsed = urlsplit(sync_url(url))
    return parsed.hostname or "127.0.0.1", parsed.port or 5432


def available(url: str) -> bool:
    """Return whether the configured PostgreSQL endpoint accepts a query."""
    host, port = target(url)
    try:
        with socket.create_connection((host, port), timeout=2.0):
            pass
        engine = create_engine(
            sync_url(url), pool_pre_ping=True, connect_args={"connect_timeout": 2}
        )
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


def env_target() -> tuple[str, str]:
    """Return the isolated-test host/port, honoring container service DNS."""
    database_url = os.environ.get("DATABASE_URL", "")
    default_host, default_port = target(database_url) if database_url else ("127.0.0.1", 5432)
    return (
        os.environ.get("TEST_PG_HOST", default_host),
        os.environ.get("TEST_PG_PORT", str(default_port)),
    )
