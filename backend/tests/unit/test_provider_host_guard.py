"""Provider base_url destination guard tests (backend-review §1.7 / V6).

No network egress and no DNS: hostname targets are statically checked, so
these tests are deterministic and offline-safe.
"""

from __future__ import annotations

import pytest
from app.config import Settings
from app.providers.host_guard import validate_provider_base_url
from app.shared.errors import ValidationAppError


def _settings(**overrides: object) -> Settings:
    options: dict[str, object] = {
        "app_env": "test",
        "session_secret": "host-guard-test-session-secret-32ch",
        "byok_fernet_key": "host-guard-test-byok-fernet-key==",
    }
    options.update(overrides)
    return Settings(**options)  # type: ignore[arg-type]


def test_public_https_origin_passes_strict_policy() -> None:
    verdict = validate_provider_base_url(
        "https://api.minimaxi.com", settings=_settings()
    )
    assert verdict.host == "api.minimaxi.com"
    assert verdict.port == 443
    assert verdict.addresses == frozenset()


def test_non_https_scheme_is_rejected() -> None:
    for value in (
        "ftp://api.example.com",
        "api.example.com",
        "https://user:pass@api.example.com",
        "http://user:pass@172.18.6.80:30020",
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


def test_reserved_addresses_stay_blocked_even_when_private_is_authorized() -> None:
    """240.0.0.1 is both is_private and is_private-adjacent reserved; the
    hard-block categories must win over the private opt-in (joint-review P1)."""

    for value in ("https://240.0.0.1", "https://255.255.255.255", "https://100.64.0.5"):
        with pytest.raises(ValidationAppError) as exc:
            validate_provider_base_url(
                value, settings=_settings(provider_base_url_allow_private=True)
            )
        assert exc.value.details["code"] == "PROVIDER_BASE_URL_BLOCKED_TARGET"


def test_http_is_rejected_without_a_trusted_network() -> None:
    for value in ("http://172.18.6.80:30020", "http://8.8.8.8"):
        with pytest.raises(ValidationAppError) as exc:
            validate_provider_base_url(value, settings=_settings())
        assert exc.value.details["code"] == "PROVIDER_BASE_URL_HTTP_UNTRUSTED"


def test_http_literal_inside_a_trusted_network_is_authorized() -> None:
    verdict = validate_provider_base_url(
        "http://172.18.6.80:30020",
        settings=_settings(provider_trusted_http_networks=["172.18.6.0/24"]),
    )
    assert verdict.host == "172.18.6.80"
    assert verdict.port == 30020
    assert verdict.addresses == frozenset({"172.18.6.80"})


def test_http_literal_outside_the_trusted_network_is_rejected() -> None:
    for value in ("http://172.18.6.80:30020", "http://8.8.8.8"):
        with pytest.raises(ValidationAppError) as exc:
            validate_provider_base_url(
                value, settings=_settings(provider_trusted_http_networks=["10.0.0.0/8"])
            )
        assert exc.value.details["code"] == "PROVIDER_BASE_URL_HTTP_UNTRUSTED"


def test_http_hostname_is_rejected_even_with_a_trusted_network() -> None:
    with pytest.raises(ValidationAppError) as exc:
        validate_provider_base_url(
            "http://models.internal:30020",
            settings=_settings(provider_trusted_http_networks=["172.18.6.0/24"]),
        )
    assert exc.value.details["code"] == "PROVIDER_BASE_URL_HTTP_UNTRUSTED"


def test_http_hard_blocked_targets_are_rejected_even_when_trusted() -> None:
    with pytest.raises(ValidationAppError) as exc:
        validate_provider_base_url(
            "http://169.254.169.254",
            settings=_settings(provider_trusted_http_networks=["169.254.0.0/16"]),
        )
    assert exc.value.details["code"] == "PROVIDER_BASE_URL_BLOCKED_TARGET"


def test_shared_address_cannot_be_authorized_by_a_trusted_http_network() -> None:
    with pytest.raises(ValidationAppError) as exc:
        validate_provider_base_url(
            "http://100.64.0.5",
            settings=_settings(provider_trusted_http_networks=["100.64.0.0/10"]),
        )
    assert exc.value.details["code"] == "PROVIDER_BASE_URL_BLOCKED_TARGET"


def test_whole_address_space_trust_is_rejected_by_settings() -> None:
    with pytest.raises(ValueError, match="whole address space"):
        Settings(
            app_env="test",
            session_secret="host-guard-test-session-secret-32ch",
            byok_fernet_key="host-guard-test-byok-fernet-key==",
            provider_trusted_http_networks=["0.0.0.0/0"],
        )


def test_invalid_trusted_network_entries_are_rejected_by_settings() -> None:
    with pytest.raises(ValueError, match="not a valid network"):
        Settings(
            app_env="test",
            session_secret="host-guard-test-session-secret-32ch",
            byok_fernet_key="host-guard-test-byok-fernet-key==",
            provider_trusted_http_networks=["not-a-network"],
        )


def test_trusted_networks_are_canonicalized() -> None:
    settings = _settings(provider_trusted_http_networks=["172.18.6.5/24"])
    assert settings.provider_trusted_http_networks == ["172.18.6.0/24"]
    assert len(settings.provider_trusted_network_objects()) == 1


def test_trusted_networks_load_from_documented_environment(monkeypatch) -> None:
    monkeypatch.setenv("PROVIDER_TRUSTED_HTTP_NETWORKS", "172.18.6.0/24, fd00::/64")
    settings = _settings()
    assert settings.provider_trusted_http_networks == ["172.18.6.0/24", "fd00::/64"]
