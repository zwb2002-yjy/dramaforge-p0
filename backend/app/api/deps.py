"""Request-scoped FastAPI dependencies (auth/RLS land in S1)."""

from app.config import Settings, get_settings


def settings_dep() -> Settings:
    return get_settings()
