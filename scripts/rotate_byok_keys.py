#!/usr/bin/env python3
"""Re-encrypt persisted BYOK credentials using the configured keyring.

Set ``BYOK_PRIMARY_KEY_VERSION`` and ``BYOK_KEYRING`` to include both the old
and new keys, run this command, verify its metadata-only report, then remove
the retired version from ``BYOK_KEYRING``. This command never prints keys or
ciphertexts.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from app.config import get_settings  # noqa: E402
from app.security.byok_keyring import parse_keyring  # noqa: E402
from app.security.credentials import rotate_credentials  # noqa: E402
from app.shared.model_registry import load_all_models  # noqa: E402


ROTATION_ROLE = "dramaforge_byok_rotation"


def _rotation_session_factory(
    database_url: str,
) -> tuple[async_sessionmaker[AsyncSession], AsyncEngine]:
    """Create an isolated maintenance engine, never reusing the app pool."""
    engine = create_async_engine(
        database_url,
        pool_pre_ping=True,
        connect_args={"ssl": False},
    )
    return (
        async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False),
        engine,
    )


async def _activate_rotation_role(session: AsyncSession) -> None:
    """Require the constrained maintenance role before credential access."""
    await session.execute(text(f"SET LOCAL ROLE {ROTATION_ROLE}"))
    bypasses_rls = await session.scalar(
        text("SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user")
    )
    if bypasses_rls is not True:
        raise RuntimeError(
            "BYOK rotation requires the dramaforge_byok_rotation maintenance role"
        )


async def _rotate(actor_label: str) -> dict[str, object]:
    # Rotation touches credential rows with workspace foreign keys. Load the
    # complete registry so SQLAlchemy can resolve those mappings when flushing.
    load_all_models()
    settings = get_settings()
    keyring = parse_keyring(
        primary_version=settings.byok_primary_key_version,
        encoded=settings.byok_keyring,
        legacy_key=settings.byok_fernet_key,
    )
    database_url = settings.byok_rotation_database_url.strip()
    if not database_url:
        raise RuntimeError(
            "BYOK_ROTATION_DATABASE_URL is required and must use a maintenance login"
        )
    factory, engine = _rotation_session_factory(database_url)
    try:
        async with factory() as session:
            await _activate_rotation_role(session)
            result = await rotate_credentials(
                session,
                keyring=keyring,
                actor_label=actor_label,
            )
            await session.commit()
    finally:
        await engine.dispose()
    return {
        "ok": True,
        "primary_key_version": keyring.primary_version,
        "readable_key_versions": list(keyring.readable_versions),
        "scanned": result.scanned,
        "reencrypted": result.reencrypted,
        "already_primary": result.already_primary,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--actor-label", required=True, help="Audit label; never a secret")
    args = parser.parse_args()
    report = asyncio.run(_rotate(args.actor_label.strip()))
    print(json.dumps(report, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
