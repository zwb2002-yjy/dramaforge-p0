"""Legacy SQL lower() keys converge to current casefold without losing links."""

import asyncio
import uuid

import pytest
from sqlalchemy import create_engine, text
from test_rls_invariant_hardening_pg import (
    _alembic,
    _create_db,
    _db_sync_url,
    _drop_db,
)
from test_rls_invariant_hardening_pg import pytestmark as pytestmark


@pytest.mark.parametrize("canonical_exists,legacy_name", [
    (False, "Straße"), (True, "Straße"), (False, "ﬃ" * 80),
])
def test_asset_tag_casefold_migration_preserves_all_asset_associations(
    canonical_exists, legacy_name,
) -> None:
    dbname = "tag_casefold_" + uuid.uuid4().hex[:12]
    try:
        asyncio.run(_create_db(dbname))
        _alembic(dbname, "upgrade", "20261030_0095")
        engine = create_engine(_db_sync_url(dbname))
        try:
            with engine.begin() as conn:
                owner = conn.execute(text("INSERT INTO users(email, display_name, password_hash) "
                    "VALUES ('tag-owner@example.com', 'Owner', 'x') RETURNING id")).scalar_one()
                workspace = conn.execute(text("INSERT INTO workspaces(owner_user_id, name) "
                    "VALUES (:u, 'Tags') RETURNING id"), {"u": owner}).scalar_one()
                project = conn.execute(text("INSERT INTO projects "
                    "(workspace_id, name, aspect_ratio, budget_limit) "
                    "VALUES (:w, 'Tags', '16:9', 0) RETURNING id"), {"w": workspace}).scalar_one()
                tags = []
                spellings = [(legacy_name, legacy_name.lower())]
                if canonical_exists:
                    spellings.append(("STRASSE", "strasse"))
                for name, normalized in spellings:
                    tags.append(conn.execute(text("INSERT INTO asset_tags "
                        "(project_id, name, normalized_name) VALUES (:p, :n, :k) RETURNING id"),
                        {"p": project, "n": name, "k": normalized}).scalar_one())
                assets = []
                for i in range(2):
                    asset = conn.execute(text("INSERT INTO assets(project_id, kind, name) "
                        "VALUES (:p, 'character', :n) RETURNING id"),
                        {"p": project, "n": f"Lead {i}"}).scalar_one()
                    assets.append(asset)
                    conn.execute(text(
                        "INSERT INTO asset_tag_links(asset_id, tag_id) VALUES (:a, :t)"
                    ), {"a": asset, "t": tags[min(i, len(tags) - 1)]})
                # The same association may already exist on both spellings.
                if canonical_exists:
                    conn.execute(text(
                        "INSERT INTO asset_tag_links(asset_id, tag_id) VALUES (:a, :t)"
                    ), {"a": assets[0], "t": tags[-1]})
            _alembic(dbname, "upgrade", "head")
            with engine.connect() as conn:
                assert conn.execute(text("SELECT id, normalized_name FROM asset_tags "
                    "WHERE project_id = :p"), {"p": project}).all() == [
                        (tags[-1], legacy_name.casefold())
                    ]
                links = conn.execute(text("SELECT asset_id, tag_id FROM asset_tag_links "
                    "WHERE asset_id IN (:a, :b)"), {"a": assets[0], "b": assets[1]}).all()
                assert set(links) == {(asset, tags[-1]) for asset in assets}
            # A repeated upgrade is idempotent; schema autogeneration stays empty.
            _alembic(dbname, "upgrade", "head")
            _alembic(dbname, "check")
            if len(legacy_name.casefold()) > 80:
                with pytest.raises(AssertionError, match="canonical tag keys longer than 80"):
                    _alembic(dbname, "downgrade", "20261030_0095")
            else:
                _alembic(dbname, "downgrade", "20261030_0095")
                _alembic(dbname, "upgrade", "head")
        finally:
            engine.dispose()
    finally:
        asyncio.run(_drop_db(dbname))
