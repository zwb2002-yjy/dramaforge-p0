"""Canonicalize Asset lifecycle states and migrate legacy metadata tags."""

from alembic import op

revision = "20260916_0070"
down_revision = "20260915_0069"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE assets
        SET status = CASE
            WHEN status = 'archived' THEN 'recycled'
            WHEN status IN ('draft', 'active', 'recycled') THEN status
            ELSE 'draft'
        END
        """
    )
    op.execute(
        """
        UPDATE asset_versions
        SET status = 'historical'
        WHERE status NOT IN ('candidate', 'formal', 'historical', 'rejected')
        """
    )
    op.execute(
        """
        WITH preferred AS (
            SELECT
                a.id AS asset_id,
                COALESCE(
                    (
                        SELECT current_av.id
                        FROM asset_versions current_av
                        WHERE current_av.id = a.current_version_id
                          AND current_av.asset_id = a.id
                          AND current_av.status IN ('formal', 'historical')
                    ),
                    (
                        SELECT av.id
                        FROM asset_versions av
                        WHERE av.asset_id = a.id
                          AND av.status IN ('formal', 'historical')
                        ORDER BY av.version_number DESC
                        LIMIT 1
                    )
                ) AS version_id
            FROM assets a
        )
        UPDATE asset_versions av
        SET status = CASE
            WHEN av.id = preferred.version_id THEN 'formal'
            WHEN av.status = 'formal' THEN 'historical'
            ELSE av.status
        END
        FROM preferred
        WHERE av.asset_id = preferred.asset_id
          AND preferred.version_id IS NOT NULL
          AND (av.id = preferred.version_id OR av.status = 'formal')
        """
    )
    op.execute(
        """
        WITH preferred AS (
            SELECT
                a.id AS asset_id,
                (
                    SELECT av.id
                    FROM asset_versions av
                    WHERE av.asset_id = a.id
                      AND av.status = 'formal'
                    ORDER BY av.version_number DESC
                    LIMIT 1
                ) AS version_id
            FROM assets a
        )
        UPDATE assets a
        SET current_version_id = preferred.version_id
        FROM preferred
        WHERE a.id = preferred.asset_id
          AND a.current_version_id IS DISTINCT FROM preferred.version_id
        """
    )

    # Preserve tags written by the former frontend exactly once, then leave
    # asset_tags + asset_tag_links as the only runtime source of truth.
    op.execute(
        """
        INSERT INTO asset_tags (project_id, name, normalized_name)
        SELECT DISTINCT a.project_id, btrim(tag.value), lower(btrim(tag.value))
        FROM assets a
        CROSS JOIN LATERAL jsonb_array_elements_text(
            CASE
                WHEN jsonb_typeof(a.metadata -> 'tags') = 'array'
                THEN a.metadata -> 'tags'
                ELSE '[]'::jsonb
            END
        ) AS tag(value)
        WHERE btrim(tag.value) <> ''
        ON CONFLICT (project_id, normalized_name) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO asset_tag_links (asset_id, tag_id)
        SELECT DISTINCT a.id, t.id
        FROM assets a
        CROSS JOIN LATERAL jsonb_array_elements_text(
            CASE
                WHEN jsonb_typeof(a.metadata -> 'tags') = 'array'
                THEN a.metadata -> 'tags'
                ELSE '[]'::jsonb
            END
        ) AS tag(value)
        JOIN asset_tags t
          ON t.project_id = a.project_id
         AND t.normalized_name = lower(btrim(tag.value))
        WHERE btrim(tag.value) <> ''
        ON CONFLICT (asset_id, tag_id) DO NOTHING
        """
    )

    op.create_check_constraint(
        "ck_assets_status",
        "assets",
        "status IN ('draft','active','recycled')",
    )
    op.create_check_constraint(
        "ck_asset_versions_status",
        "asset_versions",
        "status IN ('candidate','formal','historical','rejected')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_asset_versions_status", "asset_versions", type_="check")
    op.drop_constraint("ck_assets_status", "assets", type_="check")
