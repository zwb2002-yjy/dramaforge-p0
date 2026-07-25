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

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from app.config import get_settings  # noqa: E402
from app.security.byok_keyring import parse_keyring  # noqa: E402
from app.security.credentials import rotate_credentials  # noqa: E402
from app.shared.db import get_session_factory  # noqa: E402
from app.shared.model_registry import load_all_models  # noqa: E402


async def _rotate(actor_label: str) -> dict[str, object]:
    # Rotation touches credential rows with organization foreign keys. Load the
    # complete registry so SQLAlchemy can resolve those mappings when flushing.
    load_all_models()
    settings = get_settings()
    keyring = parse_keyring(
        primary_version=settings.byok_primary_key_version,
        encoded=settings.byok_keyring,
        legacy_key=settings.byok_fernet_key,
    )
    factory = get_session_factory(settings)
    async with factory() as session:
        result = await rotate_credentials(
            session,
            keyring=keyring,
            actor_label=actor_label,
        )
        await session.commit()
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
