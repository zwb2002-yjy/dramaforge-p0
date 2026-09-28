"""Maintenance command for immutable media catalog revisions.

Default is a read-only comparison. The caller must explicitly pass ``--apply``
and use a maintenance DB role with catalog write privileges.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.providers.catalog_sync import sync_model_catalog


async def _run(*, apply: bool) -> None:
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")
    engine = create_async_engine(database_url)
    try:
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            result = await sync_model_catalog(session, apply=apply)
            if apply:
                await session.commit()
            else:
                await session.rollback()
            print(
                json.dumps(
                    {
                        "applied": apply,
                        "inserted": result.inserted,
                        "lifecycle_updated": result.lifecycle_updated,
                        "unchanged": result.unchanged,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compare or apply media catalog revisions")
    parser.add_argument("--apply", action="store_true", help="Commit catalog changes")
    args = parser.parse_args()
    asyncio.run(_run(apply=args.apply))
