"""Dependencies must honour the settings the running app was created with."""

from __future__ import annotations

from types import SimpleNamespace

from app.api import deps
from app.config import Settings, get_settings


def test_settings_dependency_prefers_the_app_state(monkeypatch) -> None:
    configured = get_settings().model_copy(update={"app_env": "test", "source_commit": "app-state"})
    monkeypatch.setattr(
        deps,
        "get_settings",
        lambda: get_settings().model_copy(update={"source_commit": "process-cache"}),
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=configured)))
    assert deps.settings_dep(request) is configured


def test_settings_dependency_falls_back_to_the_process_cache() -> None:
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    resolved = deps.settings_dep(request)
    assert isinstance(resolved, Settings)
    assert resolved is get_settings()
