#!/usr/bin/env python3
"""Stage B5 switchover coverage report for the unified provider path.

Before flipping ``PROVIDER_UNIFIED_PATH_ENABLED=1`` every project that runs media
nodes must have an explicit ``ProjectProviderBinding`` (keyframe + video) pointing
at a fully verified Model Binding — the unified path fails closed with
``MODEL_BINDING_MISSING`` otherwise. This script reports coverage so operators
can bind projects (via the existing provider-binding API) before enabling.

Read-only: connects with DATABASE_URL, queries, prints a table. Never writes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from sqlalchemy import create_engine, text

DEFAULT_URL = "postgresql+psycopg://dramaforge:dramaforge@127.0.0.1:5432/dramaforge"


@dataclass(frozen=True)
class ProjectCoverage:
    project_id: str
    project_name: str
    workspace_id: str
    purpose: str
    binding_count: int
    verified_binding: bool


def _sync_url() -> str:
    url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    return (
        url.replace("postgresql+asyncpg://", "postgresql+psycopg://")
        .replace("postgresql+psycopg2://", "postgresql+psycopg://")
    )


def report_rows(engine: Any) -> list[ProjectCoverage]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT
                  p.id::text AS project_id,
                  p.name AS project_name,
                  p.workspace_id::text AS workspace_id,
                  pp.purpose,
                  COUNT(b.id) AS binding_count,
                  bool_and(
                    b.enabled AND b.documented AND b.contract_tested
                    AND b.account_verified AND b.quality_gated
                  ) AS verified_binding
                FROM projects p
                LEFT JOIN project_provider_bindings pp
                  ON pp.project_id = p.id
                LEFT JOIN provider_model_bindings b
                  ON b.id = pp.model_binding_id
                GROUP BY p.id, p.name, p.workspace_id, pp.purpose
                ORDER BY p.name, pp.purpose
                """
            )
        ).mappings().all()
    return [
        ProjectCoverage(
            project_id=r["project_id"],
            project_name=r["project_name"],
            workspace_id=r["workspace_id"],
            purpose=r["purpose"],
            binding_count=int(r["binding_count"] or 0),
            verified_binding=bool(r["verified_binding"]),
        )
        for r in rows
    ]


def main() -> int:
    engine = create_engine(_sync_url(), pool_pre_ping=True)
    try:
        rows = report_rows(engine)
    finally:
        engine.dispose()

    total_projects = {r.project_id for r in rows}
    bound = {r.project_id for r in rows if r.verified_binding}
    print("Stage B5 unified-path switchover coverage report")
    print("=" * 72)
    for row in sorted(rows, key=lambda r: (r.project_name, r.purpose)):
        status = "VERIFIED" if row.verified_binding else "MISSING"
        print(
            f"  {row.project_name:<28} purpose={row.purpose or '-':<10} "
            f"bindings={row.binding_count} {status}"
        )
    print("-" * 72)
    print(
        f"projects total={len(total_projects)} fully-bound={len(bound)} "
        f"missing={len(total_projects - bound)}"
    )
    missing = sorted(total_projects - bound)
    if missing:
        print("Projects missing a verified keyframe/video binding (must bind before switch):")
        for project_id in missing:
            print(f"  - {project_id}")
        return 1
    print("OK: every project has a verified binding.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
