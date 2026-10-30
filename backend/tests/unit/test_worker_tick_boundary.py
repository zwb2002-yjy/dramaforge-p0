from unittest.mock import AsyncMock

import pytest
from app.config import clear_settings_cache
from app.runtime.scheduler import WorkerRuntime


@pytest.mark.parametrize("environment", ["production", "test"])
def test_worker_tick_never_runs_jobs_outside_development(client, monkeypatch, environment):
    from cryptography.fernet import Fernet

    monkeypatch.setenv("APP_ENV", environment)
    monkeypatch.setenv("SESSION_SECRET", "s" * 48)
    monkeypatch.setenv("WORKER_TOKEN", "t" * 48)
    monkeypatch.setenv("BYOK_FERNET_KEY", Fernet.generate_key().decode())
    clear_settings_cache()
    process = AsyncMock(return_value=1)
    monkeypatch.setattr(WorkerRuntime, "process_queued", process)
    try:
        response = client.post("/api/v1/worker/tick", headers={"X-Worker-Token": "t" * 48})
        assert response.status_code == 403
        process.assert_not_awaited()
    finally:
        clear_settings_cache()
