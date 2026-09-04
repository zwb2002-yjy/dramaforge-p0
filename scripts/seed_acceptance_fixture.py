#!/usr/bin/env python3
"""P10-06 golden professional acceptance project seeder (plan 03 §93).

Seeds the deterministic Golden Professional Project into the configured
PostgreSQL (development database by default) and prints the project id and
element counts. No provider calls, no secrets.

Usage:
  APP_ENV=development backend\\.venv\\Scripts\\python.exe scripts/seed_acceptance_fixture.py
  DATABASE_URL=postgresql+asyncpg://user:pass@host/db ... scripts/seed_acceptance_fixture.py
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from uuid import uuid4

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
sys.path.insert(0, str(BACKEND))

DEFAULT_URL = "postgresql+asyncpg://dramaforge:dramaforge@127.0.0.1:5432/dramaforge"


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Seed the P10-06 golden professional project."
    )
    parser.add_argument(
        "--suffix", default=None, help="Deterministic suffix (default: random)"
    )
    args = parser.parse_args()

    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )
    from app.production.golden_project import seed_golden_project

    url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    engine = create_async_engine(url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        golden = await seed_golden_project(
            session, suffix=args.suffix or uuid4().hex[:8]
        )
        await session.commit()
        print(
            json_dumps(
                {
                    "project_id": str(golden.project.id),
                    "scenes": len(golden.scenes),
                    "shots": len(golden.shots),
                    "character_refs": len(golden.references),
                    "scene_assets": len(golden.scene_assets),
                    "formal_keyframe": str(golden.keyframe.id),
                    "formal_video": str(golden.video.id),
                    "experiment_id": str(golden.experiment.id),
                    "proposal_id": str(golden.proposal.id),
                    "edit_session_id": str(golden.edit_session_id),
                    "export_id": str(golden.export.id),
                }
            )
        )
    await engine.dispose()
    return 0


def json_dumps(value: object) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
