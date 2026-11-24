"""Resolve a fixed library member without entering the source project's private scope."""

import hashlib
from functools import lru_cache
from pathlib import Path
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.from_artifact_service import MediaSource
from app.assets.public_assets import _sqlite_public_item_sql
from app.shared.errors import NotFoundError, ValidationAppError
from app.shared.vision import PublicVisionInput


@lru_cache(maxsize=1)
def _sqlite_sql() -> str:
    library = _sqlite_public_item_sql(publication="NULL")
    template = Path(__file__).with_name("sql") / "public_vision_v1.sql"
    return template.read_text(encoding="utf-8").format(
        schema="", project=":project", item=":item", link=":link", preview=":preview",
        permitted=library, row_lock="", lock_ctes="", lock_check="",
        external_use="EXISTS (SELECT 1 FROM json_each(r.allowed_uses) "
                     "WHERE value='external_processing')",
        revision_key="SELECT group_concat(revision_id, ',') FROM "
                     "(SELECT revision_id FROM grants ORDER BY revision_id)",
    )


async def public_visual_source(
    session: AsyncSession, project_id: UUID, part: PublicVisionInput, *,
    preview: bool = False, lock: bool = False,
) -> tuple[MediaSource, str]:
    ids = {"project": project_id, "link": part.public_asset_link_id,
           "item": part.publication_item_id}
    if session.get_bind().dialect.name == "postgresql":
        stmt = text("SELECT * FROM app.public_vision_source(:project,:link,:item,:preview,:lock)")
        params: dict[str, object] = {**ids, "preview": preview, "lock": lock}
    else:
        stmt = text(_sqlite_sql())
        scope = (await session.execute(text(
            "SELECT p.workspace_id, w.owner_user_id FROM projects p "
            "JOIN workspaces w ON p.workspace_id=w.id WHERE p.id=:project"
        ), {"project": project_id.hex})).one_or_none()
        if scope is None:
            raise NotFoundError("公共画面不可用")
        selected = session.info.get("selected_workspace_id") or scope.workspace_id
        params = {key: value.hex for key, value in ids.items()}
        params.update(preview=preview, actor=scope.owner_user_id, workspace=UUID(str(selected)).hex)
    row = (await session.execute(stmt, params)).mappings().one_or_none()
    if row is None:
        if preview:
            raise NotFoundError("公共画面不可用")
        raise ValidationAppError(
            "公共画面缺少当前外部处理许可", details={"code": "SOURCE_USE_BLOCKED"},
        )
    values = dict(row)
    fields = ("publication_revision", "link_version", "revision_key")
    revisions = [str(values.pop(key)) for key in fields]
    stamp = "|".join([str(part.public_asset_link_id), str(part.publication_item_id), *revisions])
    values.update(id=UUID(str(values["id"])), project_id=UUID(str(values["project_id"])))
    return MediaSource(**values), hashlib.sha256(stamp.encode()).hexdigest()
