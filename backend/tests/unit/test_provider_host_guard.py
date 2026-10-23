"""Provider base_url destination guard tests (backend-review §1.7 / V6).

No network egress and no DNS: hostname targets are statically checked, so
these tests are deterministic and offline-safe.
"""

from __future__ import annotations

import pytest
from app.config import Settings
from app.providers.host_guard import validate_provider_base_url
from app.shared.errors import ValidationAppError


def _settings(**overrides: bool | str) -> Settings:
    return Settings(
        app_env="test",
        session_secret="host-guard-test-session-secret-32ch",
        byok_fernet_key="host-guard-test-byok-fernet-key==",
        **overrides,
    )


def test_public_https_origin_passes_strict_policy() -> None:
    verdict = validate_provider_base_url(
        "https://api.minimaxi.com", settings=_settings()
    )
    assert verdict.host == "api.minimaxi.com"
    assert verdict.port == 443
    assert verdict.addresses == frozenset()


def test_non_https_scheme_is_rejected() -> None:
    for value in (
        "http://api.example.com",
        "ftp://api.example.com",
        "api.example.com",
        "https://user:pass@api.example.com",
    ):
        with pytest.raises(ValidationAppError) as exc:
            validate_provider_base_url(value, settings=_settings())
        assert exc.value.details["code"] == "PROVIDER_BASE_URL_INVALID"


def test_private_and_loopback_literals_are_rejected_by_default() -> None:
    for value in (
        "https://192.168.1.10",
        "https://10.0.0.5",
        "https://127.0.0.1",
        "https://[::1]",
    ):
        with pytest.raises(ValidationAppError) as exc:
            validate_provider_base_url(value, settings=_settings())
        assert exc.value.details["code"] == "PROVIDER_BASE_URL_PRIVATE_NOT_AUTHORIZED"


def test_link_local_and_metadata_targets_are_always_rejected() -> None:
    for value in (
        "https://169.254.169.254",
        "https://[fe80::1]",
        "https://metadata.google.internal",
        "https://224.0.0.1",
        "https://0.0.0.0",
    ):
        with pytest.raises(ValidationAppError) as exc:
            validate_provider_base_url(
                value, settings=_settings(provider_base_url_allow_private=True)
            )
        assert exc.value.details["code"] in {
            "PROVIDER_BASE_URL_BLOCKED_TARGET",
            "PROVIDER_BASE_URL_METADATA",
        }


def test_private_deployment_is_authorized_by_explicit_opt_in() -> None:
    for value in ("https://192.168.1.10", "https://127.0.0.1", "https://[::1]"):
        verdict = validate_provider_base_url(
            value, settings=_settings(provider_base_url_allow_private=True)
        )
        assert verdict.addresses


def test_hostname_targets_are_statically_checked_only() -> None:
    """Hostnames never require DNS at write time (offline-safe)."""

    verdict = validate_provider_base_url(
        "https://fake.example.com", settings=_settings()
    )
    assert verdict.host == "fake.example.com"
    assert verdict.addresses == frozenset()


def test_empty_value_is_rejected() -> None:
    with pytest.raises(ValidationAppError, match="must not be empty"):
        validate_provider_base_url("   ", settings=_settings())
