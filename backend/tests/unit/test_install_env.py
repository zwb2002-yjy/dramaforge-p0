from __future__ import annotations

import re
from pathlib import Path

import pytest
from app.install_env import GENERATORS, render_new_env

REPO_ROOT = Path(__file__).resolve().parents[3]


def _values(text: str) -> dict[str, str]:
    return {
        name: value
        for line in text.splitlines()
        if line and not line.startswith("#")
        for name, separator, value in [line.partition("=")]
        if separator
    }


def test_release_env_is_unique_and_bound_to_exact_images() -> None:
    template = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    kwargs = {
        "version": "0.1.0",
        "source_commit": "a" * 40,
        "backend_image": "ghcr.io/example/backend@sha256:" + "b" * 64,
        "frontend_image": "ghcr.io/example/frontend@sha256:" + "c" * 64,
    }
    first = _values(render_new_env(template, **kwargs))
    second = _values(render_new_env(template, **kwargs))

    assert first["APP_ENV"] == "production"
    assert first["DRAMAFORGE_SOURCE_COMMIT"] == "a" * 40
    assert first["DRAMAFORGE_BACKEND_IMAGE"] == kwargs["backend_image"]
    assert first["DRAMAFORGE_FRONTEND_IMAGE"] == kwargs["frontend_image"]
    assert first["DATABASE_URL"].endswith("@localhost:5432/dramaforge")
    assert first["MINIO_SECRET_KEY"] == first["MINIO_ROOT_PASSWORD"]
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}=", first["BYOK_FERNET_KEY"])
    for name in GENERATORS:
        assert first[name]
        assert first[name] != second[name]


def test_release_env_rejects_ambiguous_source_identity() -> None:
    template = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="source commit"):
        render_new_env(
            template,
            version="0.1.0",
            source_commit="main",
            backend_image="backend:v0.1.0",
            frontend_image="frontend:v0.1.0",
        )
