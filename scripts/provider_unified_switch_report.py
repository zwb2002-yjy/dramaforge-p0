#!/usr/bin/env python3
"""Stage B5 switchover coverage report for the unified provider path.

Before flipping ``PROVIDER_UNIFIED_PATH_ENABLED=1`` every project that runs media
nodes must have an explicit ``ProjectProviderBinding`` for BOTH keyframe and video
pointing at fully verified Model Bindings — the unified path fails closed with
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
    keyframe_verified: bool
    video_verified: bool

    @property
    def covered(self) -> bool:
        # A project is switchover-ready only when BOTH purposes are bound to a
        # fully verified model binding. One verified purpose is NOT enough.
        return self.keyframe_verified and self.video_verified


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
                  bool_or(
                    pp.purpose = 'keyframe' AND b.enabled AND b.documented
                    AND b.contract_tested AND b.account_verified AND b.quality_gated
                  ) AS keyframe_verified,
                  bool_or(
                    pp.purpose = 'video' AND b.enabled AND b.documented
                    AND b.contract_tested AND b.account_verified AND b.quality_gated
                  ) AS video_verified
                FROM projects p
                LEFT JOIN project_provider_bindings pp
                  ON pp.project_id = p.id
                LEFT JOIN provider_model_bindings b
                  ON b.id = pp.model_binding_id
                GROUP BY p.id, p.name, p.workspace_id
                ORDER BY p.name
                """
            )
        ).mappings().all()
    return [
        ProjectCoverage(
            project_id=r["project_id"],
            project_name=r["project_name"],
            workspace_id=r["workspace_id"],
            keyframe_verified=bool(r["keyframe_verified"]),
            video_verified=bool(r["video_verified"]),
        )
        for r in rows
    ]


def main() -> int:
    engine = create_engine(_sync_url(), pool_pre_ping=True)
    try:
        rows = report_rows(engine)
    finally:
        engine.dispose()

    print("Stage B5 unified-path switchover coverage report")
    print("=" * 76)
    for row in sorted(rows, key=lambda r: r.project_name):
        status = "COVERED" if row.covered else "MISSING"
        print(
            f"  {row.project_name:<30} keyframe={'Y' if row.keyframe_verified else '-'} "
            f"video={'Y' if row.video_verified else '-'} {status}"
        )
    print("-" * 76)
    covered = [r for r in rows if r.covered]
    missing = [r for r in rows if not r.covered]
    print(f"projects total={len(rows)} covered={len(covered)} missing={len(missing)}")
    if missing:
        print("Projects missing a verified keyframe AND/OR video binding (bind before switch):")
        for row in missing:
            print(
                f"  - {row.project_id} (keyframe={'Y' if row.keyframe_verified else '-'} "
                f"video={'Y' if row.video_verified else '-'})"
            )
        return 1
    print("OK: every project has verified keyframe + video bindings.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
