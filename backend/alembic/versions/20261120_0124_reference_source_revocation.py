"""Recheck current source permissions at reference-token redemption."""

from alembic import op

revision = "20261120_0124"
down_revision = "20261119_0123"
branch_labels = None
depends_on = None

_BASE = """
CREATE OR REPLACE FUNCTION app.artifact_reference_for_token(p_token_hash text)
        RETURNS TABLE(artifact_id uuid, project_id uuid, object_key text, mime_type varchar,
                      content_hash varchar, expires_at timestamptz,
                      publication_id uuid, publication_item_id uuid,
                      public_asset_link_id uuid)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
          SELECT a.id, a.project_id, a.object_key, a.mime_type,
                 a.content_hash::varchar, t.expires_at,
                 t.publication_id, t.publication_item_id, t.public_asset_link_id
          FROM artifact_reference_tokens t
          JOIN artifacts a ON a.id = t.artifact_id
          LEFT JOIN public_asset_publications p ON p.id = t.publication_id
          LEFT JOIN project_public_asset_links l ON l.id = t.public_asset_link_id
          LEFT JOIN asset_versions v ON v.id = p.source_asset_version_id
          WHERE t.token_hash = p_token_hash
            AND t.expires_at > now()
            AND a.storage_state = 'available'
            AND a.deleted_at IS NULL
            AND (
              t.publication_id IS NULL
              OR (p.status = 'available' AND p.withdrawn_at IS NULL
                  AND l.detached_at IS NULL AND v.status = 'formal')
            )
"""

_SOURCE_CHECK = """
            AND NOT EXISTS (
                WITH RECURSIVE media(id, depth) AS (
        SELECT a.id, 0
        UNION
        SELECT s.artifact_id, m.depth + 1
        FROM media m
        JOIN artifact_source_uses u ON u.artifact_id = m.id
        JOIN source_use_subjects s ON s.id = u.source_subject_id
        WHERE s.artifact_id IS NOT NULL AND m.depth < 33
    ), bounded AS (SELECT id, depth FROM media LIMIT 1025),
    required(id) AS (
        SELECT s.id FROM bounded m JOIN source_use_subjects s ON s.artifact_id = m.id
        UNION
        SELECT u.source_subject_id FROM bounded m
          JOIN artifact_source_uses u ON u.artifact_id = m.id
          LIMIT 1025
    )
    SELECT 1 FROM required q
    LEFT JOIN source_use_subjects s ON s.id = q.id
    LEFT JOIN source_use_revisions r ON r.id = s.current_revision_id AND r.subject_id = s.id
    WHERE r.state IS DISTINCT FROM 'declared'
       OR NOT (r.allowed_uses @> '["external_processing"]'::jsonb)
       OR (t.publication_id IS NOT NULL AND NOT (r.allowed_uses @> '["library_reference"]'::jsonb))
    UNION ALL SELECT 1 WHERE t.publication_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM required)
    UNION ALL SELECT 1 FROM bounded WHERE depth > 32
    UNION ALL SELECT 1 WHERE (SELECT count(*) FROM bounded) > 1024
    UNION ALL SELECT 1 WHERE (SELECT count(*) FROM required) > 1024
            )
"""


def upgrade() -> None:
    op.execute(_BASE + _SOURCE_CHECK + "$$")


def downgrade() -> None:
    op.execute(_BASE + "$$")
