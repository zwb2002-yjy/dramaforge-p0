"""Remove the retired face-review node type from PostgreSQL."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260917_0071"
down_revision: str | None = "20260916_0070"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Rebuild the enum after 0029 migrated all historical rows."""
    op.execute("ALTER TYPE node_type RENAME TO node_type_retired")
    op.execute(
        "CREATE TYPE node_type AS ENUM ("
        "'prompt_compose', 'keyframe', 'identity_review', 'video', 'video_review', "
        "'voice', 'subtitle', 'composite', 'continuity_review', 'export')"
    )
    op.execute(
        "ALTER TABLE graph_nodes ALTER COLUMN node_type TYPE node_type "
        "USING node_type::text::node_type"
    )
    op.execute("DROP TYPE node_type_retired")
    # These types were created by the original export migration, but the
    # canonical Export ORM has always stored both fields as strings.
    op.execute("DROP TYPE IF EXISTS export_format")
    op.execute("DROP TYPE IF EXISTS export_status")


def downgrade() -> None:
    op.execute("ALTER TYPE node_type RENAME TO node_type_current")
    op.execute(
        "CREATE TYPE node_type AS ENUM ("
        "'prompt_compose', 'keyframe', 'identity_review', 'face_review', 'video', "
        "'video_review', 'voice', 'subtitle', 'composite', 'continuity_review', 'export')"
    )
    op.execute(
        "ALTER TABLE graph_nodes ALTER COLUMN node_type TYPE node_type "
        "USING node_type::text::node_type"
    )
    op.execute("DROP TYPE node_type_current")
    op.execute(
        "CREATE TYPE export_format AS ENUM ("
        "'mp4', 'srt', 'asset_package', 'timeline_json', 'jianying_draft', "
        "'davinci_fcpxml', 'edl', 'aaf')"
    )
    op.execute(
        "CREATE TYPE export_status AS ENUM ("
        "'queued', 'running', 'completed', 'failed', 'cancelled')"
    )
