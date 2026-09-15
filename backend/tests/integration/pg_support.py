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


def database_url(driver: str = "postgresql+asyncpg") -> str:
    """Resolve the PostgreSQL URL the integration suite should talk to.

    ``TEST_PG_HOST``/``TEST_PG_PORT``/``TEST_PG_USER``/``TEST_PG_PASSWORD`` take
    precedence so the same suite can run against an isolated container service
    name instead of a published host port.  When a test needs its own database it
    replaces only the path with :func:`database_url_for`.

    Six legacy PG modules hard-coded ``127.0.0.1:5432`` while every module added
    later honored ``TEST_PG_*``.  The difference was not cosmetic: in a container
    run the hard-coded ones silently probed localhost, skipped, and still reported
    a green suite -- so ~40 PostgreSQL proofs (RLS isolation, concurrent insert,
    recovery matrix, golden project, migration audit) were not running at all.
    """
    explicit = os.environ.get("DATABASE_URL", "")
    if explicit:
        if driver != "postgresql+asyncpg":
            return sync_url(explicit).replace("postgresql+psycopg://", f"{driver}://")
        return explicit
    user = os.environ.get("TEST_PG_USER", "dramaforge")
    password = os.environ.get("TEST_PG_PASSWORD", "dramaforge")
    host, port = env_target()
    return f"{driver}://{user}:{password}@{host}:{port}/dramaforge"


def database_url_for(dbname: str, driver: str = "postgresql+asyncpg") -> str:
    """The isolated-test URL with the database name replaced by ``dbname``."""
    base = database_url(driver)
    head, _, _tail = base.rpartition("/")
    return f"{head}/{dbname}"


def alembic_head() -> str:
    """Revision id the migration chain currently ends at.

    Migration tests must not hard-code a head: a new revision would make them
    assert a stale value and fail for the wrong reason. Asserting against the
    real chain keeps the check meaningful ("upgrade head reaches the chain's
    head") without coupling every future migration to three test files.
    """
    head = _alembic_script().get_current_head()
    if head is None:
        raise AssertionError("migration chain has no head")
    return head


def alembic_ancestor(steps: int) -> str:
    """Revision ``steps`` ancestors before the current head (0 == head)."""
    script = _alembic_script()
    revision = alembic_head()
    for _ in range(steps):
        parent = script.get_revision(revision).down_revision
        if parent is None:
            raise AssertionError("migration chain is shorter than the requested ancestor")
        # A merge revision has several parents; follow the first deterministically.
        revision = parent.split(",")[0] if isinstance(parent, str) else parent[0]
    return revision


def alembic_parent(revision: str) -> str:
    """The revision immediately before ``revision``.

    Downgrade targets must be named by the revision a migration actually sits on
    top of. Counting steps back from the head looks equivalent but silently
    retargets itself every time a later migration is added, which makes a
    downgrade assertion pass or fail for the wrong reason.
    """
    script = _alembic_script()
    parent = script.get_revision(revision).down_revision
    if parent is None:
        raise AssertionError(f"revision {revision} has no parent")
    return parent.split(",")[0] if isinstance(parent, str) else parent[0]


def _alembic_script():
    from pathlib import Path

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    backend = Path(__file__).resolve().parents[2]
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "alembic"))
    return ScriptDirectory.from_config(config)
