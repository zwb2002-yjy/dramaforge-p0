"""Regression coverage for the standalone BYOK rotation command."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def test_rotation_cli_loads_models_before_opening_rotation_session(monkeypatch) -> None:
    import rotate_byok_keys

    events: list[str] = []

    class Session:
        async def __aenter__(self) -> Session:
            events.append("session_enter")
            return self

        async def __aexit__(self, *args: object) -> None:
            events.append("session_exit")

        async def commit(self) -> None:
            events.append("commit")

        async def execute(self, *args: object, **kwargs: object) -> None:
            events.append("set_role")

        async def scalar(self, *args: object, **kwargs: object) -> bool:
            events.append("verify_role")
            return True

    class Engine:
        async def dispose(self) -> None:
            events.append("engine_dispose")

    def factory() -> Session:
        events.append("session_factory")
        return Session()

    monkeypatch.setattr(rotate_byok_keys, "load_all_models", lambda: events.append("models"))
    monkeypatch.setattr(
        rotate_byok_keys,
        "get_settings",
        lambda: SimpleNamespace(
            byok_primary_key_version="v2",
            byok_keyring="v1:old,v2:new",
            byok_fernet_key="",
            byok_rotation_database_url="postgresql+asyncpg://rotation@example/credentials",
        ),
    )
    monkeypatch.setattr(rotate_byok_keys, "parse_keyring", lambda **_: SimpleNamespace(
        primary_version="v2", readable_versions=("v1", "v2")
    ))
    monkeypatch.setattr(
        rotate_byok_keys,
        "_rotation_session_factory",
        lambda _: (factory, Engine()),
    )

    async def rotate(*args: object, **kwargs: object) -> SimpleNamespace:
        events.append("rotate")
        return SimpleNamespace(scanned=1, reencrypted=1, already_primary=0)

    monkeypatch.setattr(rotate_byok_keys, "rotate_credentials", rotate)

    report = asyncio.run(rotate_byok_keys._rotate("test-rotation"))

    assert events[:5] == [
        "models",
        "session_factory",
        "session_enter",
        "set_role",
        "verify_role",
    ]
    assert events[-1] == "engine_dispose"
    assert report == {
        "ok": True,
        "primary_key_version": "v2",
        "readable_key_versions": ["v1", "v2"],
        "scanned": 1,
        "reencrypted": 1,
        "already_primary": 0,
    }


def test_rotation_cli_requires_dedicated_maintenance_dsn(monkeypatch) -> None:
    import rotate_byok_keys

    monkeypatch.setattr(rotate_byok_keys, "load_all_models", lambda: None)
    monkeypatch.setattr(
        rotate_byok_keys,
        "get_settings",
        lambda: SimpleNamespace(
            byok_primary_key_version="v2",
            byok_keyring="v1:old,v2:new",
            byok_fernet_key="",
            byok_rotation_database_url="",
        ),
    )
    monkeypatch.setattr(rotate_byok_keys, "parse_keyring", lambda **_: object())

    with pytest.raises(RuntimeError, match="BYOK_ROTATION_DATABASE_URL"):
        asyncio.run(rotate_byok_keys._rotate("test-rotation"))
