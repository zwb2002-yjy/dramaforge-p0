"""Alembic environment. Migrations start with S1; BOOT-0 only keeps the project layout."""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from alembic.script import ScriptDirectory
from alembic.script.revision import RangeNotAncestorError
from app.config import get_settings
from app.shared.base import Base
from app.shared.migration_safety import require_retired_evidence_archived
from app.shared.model_registry import load_all_models
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Alembic runs in a fresh process and does not go through the API/worker
# startup imports.  Register the complete ORM graph before exposing metadata;
# otherwise ``--autogenerate`` silently sees an empty Base and cannot detect
# drift (or resolve cross-domain foreign keys).
load_all_models()
target_metadata = Base.metadata


def get_url() -> str:
    return get_settings().database_url


def crosses_evidence_cleanup(current: tuple[str, ...] | str | None) -> bool:
    destination = context.get_context().opts.get("destination_rev")
    if destination is None:
        return False
    script = ScriptDirectory.from_config(config)
    try:
        revisions = tuple(script.iterate_revisions(destination, current or "base"))
    except RangeNotAncestorError:
        # A downgrade does not traverse the destructive upgrade.
        return False
    return any(revision.revision == "20261007_0084" for revision in revisions)


def run_migrations_offline() -> None:
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        if crosses_evidence_cleanup(context.get_starting_revision_argument()):
            raise RuntimeError(
                "MODEL_MIGRATION_REQUIRES_ONLINE_PREFLIGHT: "
                "offline SQL cannot establish evidence preservation across 0084"
            )
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        if crosses_evidence_cleanup(context.get_context().get_current_heads()):
            require_retired_evidence_archived(connection)
        context.run_migrations()


async def run_async_migrations() -> None:
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = get_url()
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
