"""Director capability read-model tests: report the blocker, never a dead button."""

from __future__ import annotations

from app.config import Settings
from app.director.runtime.capabilities import (
    DIRECTOR_BLOCKER_CHECKPOINT_NOT_CONFIGURED,
    DIRECTOR_BLOCKER_ENGINE_NOT_ENABLED,
    build_director_capabilities,
)


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "app_env": "test",
        "session_secret": "test-session-secret-32chars-min",
        "byok_fernet_key": "test-byok-fernet-key-replace==",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_legacy_engine_reports_the_configuration_blocker() -> None:
    capabilities = build_director_capabilities(
        _settings(director_runtime_engine="legacy")
    )

    assert capabilities.effective_engine == "legacy"
    assert capabilities.runtime_turns_available is False
    assert capabilities.blocker_code == DIRECTOR_BLOCKER_ENGINE_NOT_ENABLED
    assert capabilities.blocker_message is not None
    assert "langgraph" in capabilities.blocker_message
    # MANUAL remains usable without the Director worker.
    assert capabilities.manual_production_available is True


def test_langgraph_without_a_checkpoint_store_is_still_blocked() -> None:
    capabilities = build_director_capabilities(
        _settings(director_runtime_engine="langgraph", director_checkpoint_database_url="")
    )

    assert capabilities.effective_engine == "langgraph"
    assert capabilities.runtime_turns_available is False
    assert capabilities.blocker_code == DIRECTOR_BLOCKER_CHECKPOINT_NOT_CONFIGURED
    assert capabilities.checkpoint_configured is False


def test_langgraph_with_a_checkpoint_store_is_available() -> None:
    capabilities = build_director_capabilities(
        _settings(
            director_runtime_engine="langgraph",
            director_checkpoint_database_url="postgresql://user:pw@db:5432/dramaforge",
        )
    )

    assert capabilities.runtime_turns_available is True
    assert capabilities.blocker_code is None
    assert capabilities.blocker_message is None
    assert capabilities.checkpoint_configured is True
    # A whitespace-only DSN is not a configured store.
    blank = build_director_capabilities(
        _settings(director_runtime_engine="langgraph", director_checkpoint_database_url="   ")
    )
    assert blank.runtime_turns_available is False
    assert blank.blocker_code == DIRECTOR_BLOCKER_CHECKPOINT_NOT_CONFIGURED


def test_capabilities_never_leak_secrets() -> None:
    capabilities = build_director_capabilities(
        _settings(
            director_runtime_engine="langgraph",
            director_checkpoint_database_url="postgresql://user:sup3rsecret@db:5432/x",
        )
    )
    payload = capabilities.model_dump(mode="json")

    def walk(value: object) -> list[str]:
        hits: list[str] = []
        if isinstance(value, dict):
            for key, child in value.items():
                normalized = str(key).casefold().replace("-", "_")
                if any(frag in normalized for frag in ("secret", "password", "dsn", "url")):
                    hits.append(key)
                hits.extend(walk(child))
        elif isinstance(value, list):
            for child in value:
                hits.extend(walk(child))
        elif isinstance(value, str) and "sup3rsecret" in value:
            hits.append("dsn value")
        return hits

    assert walk(payload) == []
