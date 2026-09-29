#!/usr/bin/env python3
"""Print an Owner-scoped, read-only early recovery inventory.

No Provider is called. The output contains IDs and gap labels, but no resume
token, remote task ID, request body, credential, or execution options.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from app.access.models import Workspace  # noqa: E402
from app.execution.recovery_inventory import build_recovery_inventory  # noqa: E402
from app.shared.db import get_engine, get_session_factory, set_rls_context  # noqa: E402
from app.shared.model_registry import load_all_models  # noqa: E402


async def _report(*, workspace_id: UUID, owner_id: UUID) -> dict[str, object]:
    load_all_models()
    factory = get_session_factory()
    try:
        async with factory() as session:
            await set_rls_context(session, user_id=owner_id, workspace_id=workspace_id)
            workspace = await session.scalar(
                select(Workspace).where(
                    Workspace.id == workspace_id,
                    Workspace.owner_user_id == owner_id,
                )
            )
            if workspace is None:
                raise ValueError("workspace is not owned by the supplied Owner")
            report = await build_recovery_inventory(session, workspace_id=workspace_id)
            await session.rollback()
            return report.to_json_dict()
    finally:
        await get_engine().dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description="Inventory recoverable ProviderOperations")
    parser.add_argument("--workspace-id", type=UUID, required=True)
    parser.add_argument("--owner-id", type=UUID, required=True)
    parser.add_argument("--out", type=Path, help="JSON report path; stdout by default")
    args = parser.parse_args()
    payload = asyncio.run(_report(workspace_id=args.workspace_id, owner_id=args.owner_id))
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.out is None:
        sys.stdout.write(encoded)
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
