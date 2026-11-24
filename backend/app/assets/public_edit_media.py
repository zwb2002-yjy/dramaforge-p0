"""Narrow project-link read shared by timeline saves, exports and render workers."""

from functools import lru_cache
from pathlib import Path
from typing import Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.from_artifact_service import MediaSource
from app.assets.render_lineage import sqlite_render_lineage


@lru_cache(maxsize=1)
def _sqlite_sql() -> str:
    root = Path(__file__).with_name("sql")
    workspace = "(SELECT workspace_id FROM projects WHERE id=:project)"
    content = (root / "public_item_content_v1.sql").read_text(encoding="utf-8").format(
        schema="", actor=f"(SELECT owner_user_id FROM workspaces WHERE id={workspace})",
        workspace=f"coalesce(:workspace, {workspace})", active_project=":project",
        project=":project", link=":link", publication="NULL", item=":item",
        permits_library="(SELECT count(DISTINCT value) FROM json_each(r.allowed_uses) "
                        "WHERE value IN ('library_reference', :purpose)) = 2",
    )
    content += " AND (" + sqlite_render_lineage("(SELECT id FROM candidate)") + ")"
    return (root / "public_edit_media_v1.sql").read_text(encoding="utf-8").format(
        content_query=content, schema="", item=":item",
        publication=":publication", purpose=":purpose",
    )


async def read_public_edit_media(
    session: AsyncSession, *, project_id: UUID, link_id: UUID, publication_id: UUID,
    item_id: UUID, purpose: Literal["creation", "export"],
) -> MediaSource | None:
    ids = {"project": project_id, "link": link_id, "publication": publication_id, "item": item_id}
    if session.get_bind().dialect.name == "postgresql":
        stmt = text(
            "SELECT * FROM app.public_edit_media(:project,:link,:publication,:item,:purpose)"
        )
        params: dict[str, object] = {**ids, "purpose": purpose}
    else:
        stmt = text(_sqlite_sql())
        workspace = session.info.get("selected_workspace_id")
        params = {key: value.hex for key, value in ids.items()}
        params.update(purpose=purpose, workspace=UUID(str(workspace)).hex if workspace else None)
    row = (await session.execute(stmt, params)).mappings().one_or_none()
    if row is None:
        return None
    values = dict(row)
    values.update(id=UUID(str(row["id"])), project_id=UUID(str(row["project_id"])))
    return MediaSource(**values)
