"""Agnes BYOK settings load without leaking secrets into assertions."""

from __future__ import annotations

import os

from app.config import Settings, clear_settings_cache
from app.providers.flux import get_flux_adapter
from app.providers.kling import get_kling_adapter


def test_agnes_settings_from_env(monkeypatch: object) -> None:
    clear_settings_cache()
    monkeypatch.setenv("AGNES_ENABLED", "true")  # type: ignore[attr-defined]
    monkeypatch.setenv("AGNES_API_KEY", "sk-test-not-real")  # type: ignore[attr-defined]
    monkeypatch.setenv("AGNES_BASE_URL", "https://apihub.agnes-ai.com/v1")  # type: ignore[attr-defined]
    monkeypatch.setenv("AGNES_IMAGE_MODEL", "agnes-image-2.1-flash")  # type: ignore[attr-defined]
    monkeypatch.setenv("AGNES_VIDEO_MODEL", "agnes-video-v2.0")  # type: ignore[attr-defined]
    clear_settings_cache()
    s = Settings()
    assert s.agnes_configured() is True
    assert s.agnes_base_url.endswith("/v1")
    assert s.agnes_image_model == "agnes-image-2.1-flash"
    assert s.agnes_video_model == "agnes-video-v2.0"
    # Adapter factory selects Agnes when configured
    assert get_flux_adapter().provider == "flux"
    assert get_kling_adapter().provider == "kling"
    clear_settings_cache()


def test_agnes_disabled_uses_fake(monkeypatch: object) -> None:
    clear_settings_cache()
    monkeypatch.setenv("AGNES_ENABLED", "false")  # type: ignore[attr-defined]
    monkeypatch.delenv("AGNES_API_KEY", raising=False)  # type: ignore[attr-defined]
    clear_settings_cache()
    s = Settings()
    assert s.agnes_configured() is False
    from app.providers.fake import FakeFluxAdapter

    assert isinstance(get_flux_adapter(), FakeFluxAdapter)
    clear_settings_cache()
