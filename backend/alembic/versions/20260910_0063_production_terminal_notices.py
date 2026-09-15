"""Emit terminal shot execution notices atomically from every status write path."""

from alembic import op

revision = "20260910_0063"
down_revision = "20260909_0062"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE FUNCTION app.emit_workbench_terminal_notice() RETURNS trigger
        LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
        DECLARE
          shot_uuid uuid;
          notice_id uuid;
          notice jsonb;
        BEGIN
          IF NEW.status IS NOT DISTINCT FROM OLD.status OR
             NEW.status::text NOT IN ('completed','cached','failed','cancelled','completed_after_cancel') OR
             jsonb_typeof(NEW.input_snapshot::jsonb->'workbench_plan') IS DISTINCT FROM 'object'
          THEN RETURN NEW; END IF;
          SELECT g.scope_entity_id INTO shot_uuid FROM graph_versions v
          JOIN production_graphs g ON g.id = v.graph_id
          WHERE v.id = NEW.graph_version_id AND g.project_id = NEW.project_id
            AND g.scope_type = 'shot';
          IF shot_uuid IS NULL THEN RETURN NEW; END IF;
          notice_id := gen_random_uuid();
          notice := jsonb_build_object('project_id', NEW.project_id::text,
            'actor_id', NEW.created_by::text, 'notice', jsonb_build_object(
              'kind', 'execution_changed', 'shot_id', shot_uuid::text, 'node_run_id', NEW.id::text));
          INSERT INTO event_log(id,event_id,project_id,aggregate_type,aggregate_id,event_type,
                                schema_version,actor_id,payload)
          VALUES(gen_random_uuid(),notice_id,NEW.project_id,'shot',shot_uuid,
                 'execution_changed',1,NEW.created_by,notice);
          INSERT INTO outbox_events(id,event_id,project_id,topic,schema_version,payload,status,attempt_count)
          VALUES(gen_random_uuid(),notice_id,NEW.project_id,'production.facts.v1',1,notice,'pending',0);
          RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER workbench_terminal_notice AFTER UPDATE OF status ON node_runs
        FOR EACH ROW EXECUTE FUNCTION app.emit_workbench_terminal_notice()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER workbench_terminal_notice ON node_runs")
    op.execute("DROP FUNCTION app.emit_workbench_terminal_notice()")
