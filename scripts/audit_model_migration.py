"""Read-only preflight for retired model/experiment evidence before migration 0084.

Does not apply migrations, archive data, clear tables or infer a verified backup.
"""

from __future__ import annotations

import asyncio
import json
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app.shared.migration_safety import inspect_retired_tables as inspect_connection


async def inspect_retired_tables(session):
    return await session.run_sync(lambda sync: inspect_connection(sync.connection()))


async def run() -> int:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise ValueError("DATABASE_URL is required")
    engine = create_async_engine(url)
    try:
        if engine.dialect.name != "postgresql":
            raise ValueError("PostgreSQL READ ONLY enforcement is required")
        async with async_sessionmaker(engine)() as session:
            await session.execute(text("SET TRANSACTION READ ONLY"))
            report = await inspect_retired_tables(session)
            await session.rollback()
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 1 if report["blocked_nonempty_tables"] else 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
