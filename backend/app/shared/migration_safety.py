"""Evidence preservation at the current migration entry, without rewriting history."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

RETIRED_TABLES = (
    "production_experiments",
    "shot_experiments",
    "product_policy_events",
    "product_policy_states",
    "product_policy_revisions",
    "connection_model_capability_revisions",
    "connection_discovered_models",
    "model_publication_events",
    "model_publication_states",
    "model_capability_revisions",
    "runtime_handler_revisions",
    "protocol_contract_revisions",
)


def inspect_retired_tables(connection: Connection, *, lock: bool = False) -> dict[str, Any]:
    existing = set(
        connection.execute(
            text("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
        ).scalars()
    )
    rows = []
    for table in RETIRED_TABLES:
        # Fixed identifiers only. Migration locks prevent writes between check and DROP.
        if lock and table in existing:
            connection.execute(text(f'LOCK TABLE "{table}" IN ACCESS EXCLUSIVE MODE'))
        count = (
            connection.scalar(text(f'SELECT count(*) FROM "{table}"'))
            if table in existing
            else None
        )
        rows.append(
            {
                "table": table,
                "exists": table in existing,
                "rows": count,
                "archive_required": count is not None and count > 0,
            }
        )
    return {
        "read_only": not lock,
        "target_migration": "20261007_0084",
        "blocked_nonempty_tables": [item["table"] for item in rows if item["archive_required"]],
        "tables": rows,
        "backup_restore_verified": False,
        "destructive_migration_applied": False,
    }


def require_retired_evidence_archived(connection: Connection) -> None:
    report = inspect_retired_tables(connection, lock=True)
    if report["blocked_nonempty_tables"]:
        names = ", ".join(report["blocked_nonempty_tables"])
        raise RuntimeError(
            "MODEL_MIGRATION_EVIDENCE_NOT_ARCHIVED: "
            f"{names}; archive and verify readable restoration before upgrading; "
            "this command does not archive, clear or approve deletion"
        )
