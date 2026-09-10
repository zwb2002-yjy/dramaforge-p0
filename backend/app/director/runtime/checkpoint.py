"""Project-scoped access to the private LangGraph checkpoint schema."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

import psycopg
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from app.config import Settings
from app.shared.errors import ValidationAppError

CHECKPOINT_SCHEMA = "director_runtime_checkpoints"


def scoped_checkpoint_dsn(base_dsn: str, *, project_id: UUID) -> str:
    """Return a libpq DSN whose connection is pinned to one project and schema."""

    if not base_dsn.strip() or ":disabled@" in base_dsn:
        raise ValidationAppError(
            "Director checkpoint database is not configured",
            details={"code": "DIRECTOR_CHECKPOINT_DATABASE_UNAVAILABLE"},
        )
    try:
        parameters = conninfo_to_dict(base_dsn)
    except Exception as exc:
        raise ValidationAppError(
            "Director checkpoint database configuration is invalid",
            details={"code": "DIRECTOR_CHECKPOINT_DATABASE_INVALID"},
        ) from exc
    if parameters.get("options"):
        raise ValidationAppError(
            "Director checkpoint database options must be runtime-owned",
            details={"code": "DIRECTOR_CHECKPOINT_OPTIONS_FORBIDDEN"},
        )
    return make_conninfo(
        base_dsn,
        options=(
            f"-c search_path={CHECKPOINT_SCHEMA} "
            f"-c app.project_id={project_id}"
        ),
        application_name="dramaforge-director-checkpoint",
    )


@asynccontextmanager
async def scoped_checkpointer(
    settings: Settings, *, project_id: UUID,
) -> AsyncIterator[AsyncPostgresSaver]:
    """Open an RLS-scoped saver; schema setup belongs only to Alembic."""

    dsn = scoped_checkpoint_dsn(
        settings.director_checkpoint_database_url,
        project_id=project_id,
    )
    serializer = JsonPlusSerializer(allowed_msgpack_modules=())
    async with AsyncPostgresSaver.from_conn_string(dsn, serde=serializer) as saver:
        yield saver


async def verify_checkpoint_store(settings: Settings) -> None:
    """Fail worker startup when the migrated private store is not reachable."""

    dsn = scoped_checkpoint_dsn(
        settings.director_checkpoint_database_url,
        project_id=UUID(int=0),
    )
    async with await psycopg.AsyncConnection.connect(dsn) as connection:
        row = await (await connection.execute(
            "SELECT max(v) FROM checkpoint_migrations"
        )).fetchone()
    if row is None or row[0] != 9:
        raise ValidationAppError(
            "Director checkpoint schema is not at the supported version",
            details={"code": "DIRECTOR_CHECKPOINT_SCHEMA_UNSUPPORTED"},
        )


__all__ = [
    "CHECKPOINT_SCHEMA",
    "scoped_checkpoint_dsn",
    "scoped_checkpointer",
    "verify_checkpoint_store",
]
