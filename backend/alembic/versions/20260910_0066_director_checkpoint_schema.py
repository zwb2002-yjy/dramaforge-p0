"""Provision the private, project-scoped LangGraph checkpoint schema."""

from alembic import op

revision = "20260910_0066"
down_revision = "20260910_0065"
branch_labels = None
depends_on = None

SCHEMA = "director_runtime_checkpoints"
ROLE = "dramaforge_director_checkpoint"


def upgrade() -> None:
    op.execute(f"""
        DO $$ BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}') THEN
            CREATE ROLE {ROLE} NOLOGIN NOINHERIT NOBYPASSRLS;
          END IF;
        END $$
    """)
    op.execute(f"ALTER ROLE {ROLE} NOINHERIT NOBYPASSRLS")
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    op.execute(f"REVOKE ALL ON SCHEMA {SCHEMA} FROM PUBLIC, dramaforge_app")
    op.execute(f"GRANT USAGE ON SCHEMA {SCHEMA} TO {ROLE}")
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA}.checkpoint_migrations (
          v integer PRIMARY KEY
        )
    """)
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA}.checkpoints (
          thread_id text NOT NULL,
          checkpoint_ns text NOT NULL DEFAULT '',
          checkpoint_id text NOT NULL,
          parent_checkpoint_id text,
          type text,
          checkpoint jsonb NOT NULL,
          metadata jsonb NOT NULL DEFAULT '{{}}'::jsonb,
          PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
        )
    """)
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA}.checkpoint_blobs (
          thread_id text NOT NULL,
          checkpoint_ns text NOT NULL DEFAULT '',
          channel text NOT NULL,
          version text NOT NULL,
          type text NOT NULL,
          blob bytea,
          PRIMARY KEY (thread_id, checkpoint_ns, channel, version)
        )
    """)
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA}.checkpoint_writes (
          thread_id text NOT NULL,
          checkpoint_ns text NOT NULL DEFAULT '',
          checkpoint_id text NOT NULL,
          task_id text NOT NULL,
          idx integer NOT NULL,
          channel text NOT NULL,
          type text,
          blob bytea NOT NULL,
          task_path text NOT NULL DEFAULT '',
          PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
        )
    """)
    for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
        op.execute(
            f"CREATE INDEX IF NOT EXISTS {table}_thread_id_idx "
            f"ON {SCHEMA}.{table}(thread_id)"
        )
        op.execute(f"ALTER TABLE {SCHEMA}.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {SCHEMA}.{table} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS {table}_project_scope ON {SCHEMA}.{table}")
        op.execute(f"""
            CREATE POLICY {table}_project_scope ON {SCHEMA}.{table} FOR ALL
            TO {ROLE}
            USING (
              split_part(thread_id, ':', 1) = 'dramaforge'
              AND split_part(thread_id, ':', 2) = current_setting('app.project_id', true)
            )
            WITH CHECK (
              split_part(thread_id, ':', 1) = 'dramaforge'
              AND split_part(thread_id, ':', 2) = current_setting('app.project_id', true)
            )
        """)
        op.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON {SCHEMA}.{table} TO {ROLE}"
        )
    op.execute(f"GRANT SELECT ON {SCHEMA}.checkpoint_migrations TO {ROLE}")
    op.execute(f"""
        INSERT INTO {SCHEMA}.checkpoint_migrations(v)
        SELECT generate_series(0, 9)
        ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    op.execute(f"""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM {SCHEMA}.checkpoints LIMIT 1)
             OR EXISTS (SELECT 1 FROM {SCHEMA}.checkpoint_writes LIMIT 1)
             OR EXISTS (SELECT 1 FROM {SCHEMA}.checkpoint_blobs LIMIT 1) THEN
            RAISE EXCEPTION 'cannot remove Director checkpoints while executions exist';
          END IF;
        END $$
    """)
    op.execute(f"DROP SCHEMA {SCHEMA} CASCADE")
    op.execute(f"ALTER ROLE {ROLE} NOLOGIN NOINHERIT NOBYPASSRLS PASSWORD NULL")
