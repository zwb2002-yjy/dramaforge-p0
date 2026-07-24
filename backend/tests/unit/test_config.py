"""Settings validation tests."""

from __future__ import annotations

import pytest
from app.config import Settings, clear_settings_cache
from pydantic import ValidationError


def test_default_settings_load() -> None:
    clear_settings_cache()
    settings = Settings(
        session_secret="test-session-secret-32chars-min",
        byok_fernet_key="test-byok-fernet-key-replace==",
    )
    assert settings.app_name == "DramaForge"
    assert settings.database_url.startswith("postgresql+asyncpg://")
    assert settings.arq_default_queue_name
    assert settings.arq_heavy_queue_name
    assert settings.arq_heavy_max_jobs == 4


def test_cors_origins_from_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "http://a.local, http://b.local")
    clear_settings_cache()
    settings = Settings(
        session_secret="test-session-secret-32chars-min",
        byok_fernet_key="test-byok-fernet-key-replace==",
    )
    assert settings.cors_origins == ["http://a.local", "http://b.local"]


def test_session_secret_min_length() -> None:
    with pytest.raises(ValidationError):
        Settings(session_secret="short", byok_fernet_key="test-byok-fernet-key-replace==")
