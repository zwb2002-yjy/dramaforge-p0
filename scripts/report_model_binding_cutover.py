#!/usr/bin/env python3
"""Read-only Binding classification for the cutover gate.

Owner reports are useful for remediation. The all-owners gate requires a
maintenance DB role that can see every workspace, including FORCE RLS rows.
Reports include model IDs and blocking reasons, never credentials. No Provider
is invoked.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from uuid import UUID

from sqlalchemy import func, select, text

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from app.access.models import Workspace  # noqa: E402
from app.providers.binding_cutover import build_binding_cutover_report  # noqa: E402
from app.providers.models import ProviderModelBinding  # noqa: E402
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


async def _report_all_owners() -> dict[str, object]:
    """Use one read-only snapshot; fail if RLS could hide another Owner."""
    load_all_models()
    factory = get_session_factory()
    try:
        async with factory() as session:
            if session.get_bind().dialect.name != "postgresql":
                raise RuntimeError("all-owners gate requires PostgreSQL")
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            privileged = await session.scalar(
                text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user")
            )
            if privileged is not True:
                raise PermissionError(
                    "all-owners gate requires a superuser or BYPASSRLS maintenance role"
                )
            workspaces = list(
                (
                    await session.execute(
                        select(Workspace.owner_user_id, Workspace.id).order_by(
                            Workspace.owner_user_id, Workspace.id
                        )
                    )
                ).all()
            )
            binding_count = await session.scalar(
                select(func.count()).select_from(ProviderModelBinding)
            )
            by_owner: dict[UUID, list[dict[str, object]]] = {}
            for owner_id, workspace_id in workspaces:
                await set_rls_context(session, user_id=owner_id, workspace_id=workspace_id)
                report = await build_binding_cutover_report(session, workspace_id=workspace_id)
                by_owner.setdefault(owner_id, []).append(report.to_json_dict())
            await session.rollback()
            scanned_binding_count = sum(
                len(report["bindings"]) for reports in by_owner.values() for report in reports
            )
            if scanned_binding_count != binding_count:
                raise RuntimeError("all-owners gate did not classify every Binding")
            owners: list[dict[str, object]] = []
            for owner_id, reports in by_owner.items():
                owners.append(
                    {
                        "owner_id": str(owner_id),
                        "workspace_count": len(reports),
                        "enabled_unresolved_count": sum(
                            int(item["enabled_unresolved_count"]) for item in reports
                        ),
                        "enabled_blocked_count": sum(
                            int(item["enabled_blocked_count"]) for item in reports
                        ),
                        "workspaces": reports,
                    }
                )
            return {
                "coverage": "all_owners",
                "owner_count": len(owners),
                "workspace_count": len(workspaces),
                "binding_count": scanned_binding_count,
                "enabled_unresolved_count": sum(
                    int(item["enabled_unresolved_count"]) for item in owners
                ),
                "enabled_blocked_count": sum(int(item["enabled_blocked_count"]) for item in owners),
                "owners": owners,
            }
    finally:
        await get_engine().dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description="Classify existing model bindings")
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--workspace-id", type=UUID)
    scope.add_argument("--all-workspaces", action="store_true")
    scope.add_argument("--all-owners", action="store_true")
    parser.add_argument("--owner-id", type=UUID)
    parser.add_argument(
        "--strict", action="store_true", help="exit 2 when any enabled binding blocks cutover"
    )
    parser.add_argument("--out", type=Path, help="JSON report path; stdout by default")
    args = parser.parse_args()
    if args.all_owners and args.owner_id is not None:
        parser.error("--owner-id cannot be combined with --all-owners")
    if not args.all_owners and args.owner_id is None:
        parser.error("--owner-id is required for Owner-scoped reports")
    payload = asyncio.run(
        _report_all_owners()
        if args.all_owners
        else (
            _report_all(owner_id=args.owner_id)
            if args.all_workspaces
            else _report(workspace_id=args.workspace_id, owner_id=args.owner_id)
        )
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
        or ((args.all_workspaces or args.all_owners) and int(payload["workspace_count"]) == 0)
    ):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
