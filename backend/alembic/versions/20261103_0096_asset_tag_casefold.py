"""Converge historical lower() tag keys to the runtime casefold contract.

Revision ID: 20261103_0096
Revises: 20261030_0095

Keep an already canonical vocabulary ID when present, otherwise the oldest
ID. Merge equivalent spellings within each project and union every asset
association before removing redundant vocabulary rows. No assets are deleted.
"""

from alembic import op
from sqlalchemy import String, Text, text

revision = "20261103_0096"
down_revision = "20261030_0095"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    bind.execute(text("LOCK TABLE asset_tags, asset_tag_links IN SHARE ROW EXCLUSIVE MODE"))
    # Casefold can expand a valid 80-character display name (e.g. ligatures).
    # The derived lookup key must not inherit the display field's length cap.
    op.alter_column("asset_tags", "normalized_name", existing_type=String(80), type_=Text())
    rows = bind.execute(text(
        "SELECT id, project_id, name, normalized_name FROM asset_tags ORDER BY created_at, id"
    )).mappings().all()
    groups = {}
    for row in rows:
        normalized = row["name"].strip().casefold()
        if not normalized:
            raise RuntimeError("Asset tag has an empty name; repair it before migrating")
        groups.setdefault((row["project_id"], normalized), []).append(row)
    for (_project, normalized), equivalents in groups.items():
        winner = next((row for row in equivalents if row["normalized_name"] == normalized),
                      equivalents[0])
        for row in equivalents:
            if row["id"] == winner["id"]:
                continue
            bind.execute(text(
                "INSERT INTO asset_tag_links(asset_id, tag_id, created_at) "
                "SELECT asset_id, :winner, created_at FROM asset_tag_links WHERE tag_id = :loser "
                "ON CONFLICT (asset_id, tag_id) DO UPDATE "
                "SET created_at = LEAST(asset_tag_links.created_at, EXCLUDED.created_at)"
            ), {"winner": winner["id"], "loser": row["id"]})
            bind.execute(text("DELETE FROM asset_tags WHERE id = :id"), {"id": row["id"]})
        if winner["normalized_name"] != normalized:
            bind.execute(text("UPDATE asset_tags SET normalized_name = :key WHERE id = :id"),
                         {"key": normalized, "id": winner["id"]})


def downgrade() -> None:
    # Canonical normalization and merged associations remain valid at 0095.
    # Original duplicate vocabulary IDs cannot be reconstructed from a union.
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    if bind.scalar(text("SELECT EXISTS (SELECT 1 FROM asset_tags "
                        "WHERE char_length(normalized_name) > 80)")):
        raise RuntimeError("Cannot downgrade canonical tag keys longer than 80 characters")
    op.alter_column("asset_tags", "normalized_name", existing_type=Text(), type_=String(80))
