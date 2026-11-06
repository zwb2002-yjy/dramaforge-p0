"""Read-only Provider identity preflight. No create/poll/resume or DB writes."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from uuid import UUID

from app.execution.provider_recovery_audit import audit_provider_recovery
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


async def run(*, workspace_id: UUID | None) -> None:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise ValueError("DATABASE_URL is required (maintenance read privileges only)")
    engine = create_async_engine(url)
    try:
        if engine.dialect.name != "postgresql":
            raise ValueError("CLI requires PostgreSQL transaction-level READ ONLY enforcement")
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            await session.execute(text("SET TRANSACTION READ ONLY"))
            cursor = None
            rows = []
            while True:
                page = await audit_provider_recovery(
                    session,
                    workspace_id=workspace_id,
                    after_operation_id=cursor,
                )
                rows.extend(item.as_dict() for item in page)
                if len(page) < 100:
                    break
                cursor = page[-1].operation_id
            await session.rollback()
            print(
                json.dumps(
                    {
                        "read_only": True,
                        "provider_calls": 0,
                        "identity_preflight_passed": sum(not item["blockers"] for item in rows),
                        "scanned": len(rows),
                        "operations": rows,
                        "limitations": (
                            "No credential decryption, remote state or network verification."
                        ),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--workspace-id", type=UUID)
    scope.add_argument(
        "--all-workspaces",
        action="store_true",
        help="Explicit maintenance-owner scan across workspaces",
    )
    args = parser.parse_args()
    asyncio.run(run(workspace_id=args.workspace_id))
