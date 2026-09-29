#!/usr/bin/env python3
"""Read-only, workspace-scoped Binding classification for the cutover gate.

Run once per workspace under its Owner context. The report includes model IDs
and blocking reasons, never credentials. It does not invoke a Provider.
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
from app.providers.binding_cutover import build_binding_cutover_report  # noqa: E402
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
            report = await build_binding_cutover_report(session, workspace_id=workspace_id)
            await session.rollback()
            return report.to_json_dict()
    finally:
        await get_engine().dispose()


async def _report_all(*, owner_id: UUID) -> dict[str, object]:
    """Enumerate every RLS-visible workspace owned by one Owner."""
    load_all_models()
    factory = get_session_factory()
    try:
        async with factory() as session:
            await set_rls_context(session, user_id=owner_id)
            workspace_ids = list(
                (
                    await session.scalars(
                        select(Workspace.id)
                        .where(Workspace.owner_user_id == owner_id)
                        .order_by(Workspace.id)
                    )
                ).all()
            )
            await session.rollback()
        reports: list[dict[str, object]] = []
        for workspace_id in workspace_ids:
            async with factory() as session:
                await set_rls_context(session, user_id=owner_id, workspace_id=workspace_id)
                report = await build_binding_cutover_report(session, workspace_id=workspace_id)
                reports.append(report.to_json_dict())
                await session.rollback()
        return {
            "owner_id": str(owner_id),
            "coverage": "owner_workspaces",
            "workspace_count": len(reports),
            "enabled_unresolved_count": sum(
                int(item["enabled_unresolved_count"]) for item in reports
            ),
            "enabled_blocked_count": sum(int(item["enabled_blocked_count"]) for item in reports),
            "workspaces": reports,
        }
    finally:
        await get_engine().dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description="Classify existing model bindings")
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--workspace-id", type=UUID)
    scope.add_argument("--all-workspaces", action="store_true")
    parser.add_argument("--owner-id", type=UUID, required=True)
    parser.add_argument(
        "--strict", action="store_true", help="exit 2 when any enabled binding blocks cutover"
    )
    parser.add_argument("--out", type=Path, help="JSON report path; stdout by default")
    args = parser.parse_args()
    payload = asyncio.run(
        _report_all(owner_id=args.owner_id)
        if args.all_workspaces
        else _report(workspace_id=args.workspace_id, owner_id=args.owner_id)
    )
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.out is None:
        sys.stdout.write(encoded)
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded, encoding="utf-8")
    if args.strict and (
        int(payload["enabled_unresolved_count"])
        or int(payload["enabled_blocked_count"])
        or (args.all_workspaces and int(payload["workspace_count"]) == 0)
    ):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
