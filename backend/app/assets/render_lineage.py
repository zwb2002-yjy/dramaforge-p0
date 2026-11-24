"""Read-time eligibility for new sharing of an output with historical public inputs."""

from functools import lru_cache
from pathlib import Path
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@lru_cache(maxsize=8)
def sqlite_render_lineage(root: str) -> str:
    return (
        (Path(__file__).with_name("sql") / "render_lineage_v1.sql")
        .read_text(encoding="utf-8")
        .format(
            root=root,
            schema="",
            length="json_array_length",
            json_type="json_type",
            library_allowed=("EXISTS (SELECT 1 FROM json_each(r.allowed_uses) "
                             "WHERE value='library_reference')"),
        )
    )


async def render_origins_available(
    session: AsyncSession, project_id: UUID, artifact_id: UUID
) -> bool:
    if session.get_bind().dialect.name == "postgresql":
        return bool(
            await session.scalar(
                text("SELECT app.project_render_origins(:project,:artifact)"),
                {"project": project_id, "artifact": artifact_id},
            )
        )
    return bool(
        await session.scalar(
            text(sqlite_render_lineage(":artifact")), {"artifact": artifact_id.hex}
        )
    )
