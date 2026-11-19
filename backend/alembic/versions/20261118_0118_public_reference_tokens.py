"""Public reference tokens: six-column public identity and live eligibility (I5-02).

A token issued from a project public link records the publication/item/link identity
and owner; the resolver function re-checks publication availability, link attachment
and the source version before returning bytes. Private tokens keep their four NULLs.

Revision ID: 20261118_0118
Revises: 20261118_0117
Create Date: 2026-11-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261118_0118"
down_revision: str | None = "20261118_0117"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "artifact_reference_tokens", sa.Column("publication_id", sa.UUID(), nullable=True)
    )
    op.add_column(
        "artifact_reference_tokens", sa.Column("publication_item_id", sa.UUID(), nullable=True)
    )
    op.add_column(
        "artifact_reference_tokens", sa.Column("public_asset_link_id", sa.UUID(), nullable=True)
    )
    op.add_column(
        "artifact_reference_tokens", sa.Column("owner_user_id", sa.UUID(), nullable=True)
    )
    op.create_check_constraint(
        "ck_artifact_reference_token_public_all_or_none",
        "artifact_reference_tokens",
        "(publication_id IS NULL) = (publication_item_id IS NULL) "
        "AND (publication_id IS NULL) = (public_asset_link_id IS NULL) "
        "AND (publication_id IS NULL) = (owner_user_id IS NULL)",
    )
    op.create_foreign_key(
        "fk_artifact_reference_token_publication",
        "artifact_reference_tokens",
        "public_asset_publications",
        ["publication_id", "project_id", "workspace_id", "owner_user_id"],
        ["id", "source_project_id", "workspace_id", "owner_user_id"],
    )
    op.create_foreign_key(
        "fk_artifact_reference_token_item",
        "artifact_reference_tokens",
        "public_asset_publication_items",
        ["publication_item_id", "publication_id", "artifact_id", "owner_user_id"],
        ["id", "publication_id", "artifact_id", "owner_user_id"],
    )
    op.create_foreign_key(
        "fk_artifact_reference_token_link",
        "artifact_reference_tokens",
        "project_public_asset_links",
        ["public_asset_link_id", "project_id"],
        ["id", "project_id"],
    )
    op.execute("DROP FUNCTION IF EXISTS app.artifact_reference_for_token(text)")
    op.execute(
        """
        CREATE FUNCTION app.artifact_reference_for_token(p_token_hash text)
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
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION app.artifact_reference_for_token(text) FROM PUBLIC")
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.artifact_reference_for_token(text) "
        "TO dramaforge, dramaforge_app"
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS app.artifact_reference_for_token(text)")
    op.execute(
        """
        CREATE FUNCTION app.artifact_reference_for_token(p_token_hash text)
        RETURNS TABLE(artifact_id uuid, project_id uuid, object_key text, mime_type varchar,
                      content_hash varchar, expires_at timestamptz)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
          SELECT a.id, a.project_id, a.object_key, a.mime_type,
                 a.content_hash::varchar, t.expires_at
          FROM artifact_reference_tokens t
          JOIN artifacts a ON a.id = t.artifact_id
          WHERE t.token_hash = p_token_hash
            AND t.expires_at > now()
            AND a.storage_state = 'available'
            AND a.deleted_at IS NULL
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION app.artifact_reference_for_token(text) FROM PUBLIC")
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.artifact_reference_for_token(text) "
        "TO dramaforge, dramaforge_app"
    )
    op.drop_constraint(
        "fk_artifact_reference_token_link", "artifact_reference_tokens", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_artifact_reference_token_item", "artifact_reference_tokens", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_artifact_reference_token_publication",
        "artifact_reference_tokens",
        type_="foreignkey",
    )
    op.drop_constraint(
        "ck_artifact_reference_token_public_all_or_none",
        "artifact_reference_tokens",
        type_="check",
    )
    op.drop_column("artifact_reference_tokens", "owner_user_id")
    op.drop_column("artifact_reference_tokens", "public_asset_link_id")
    op.drop_column("artifact_reference_tokens", "publication_item_id")
    op.drop_column("artifact_reference_tokens", "publication_id")
