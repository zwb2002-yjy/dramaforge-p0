"""Pytest fixtures for the backend package."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

# Ensure test-safe defaults before importing the app.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-32chars-min")
os.environ.setdefault("BYOK_FERNET_KEY", "test-byok-fernet-key-replace==")

from app.config import clear_settings_cache, get_settings  # noqa: E402
from app.main import create_app  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_settings() -> Iterator[None]:
    clear_settings_cache()
    yield
    clear_settings_cache()


@pytest.fixture
def client() -> Iterator[TestClient]:
    clear_settings_cache()
    app = create_app(get_settings())
    with TestClient(app) as test_client:
        yield test_client
