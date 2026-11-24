from uuid import uuid4

import pytest
from app.config import Settings
from app.main import create_app
from app.shared.runtime_admission import process_facts
from fastapi.testclient import TestClient
from pydantic import ValidationError


@pytest.mark.parametrize(
    ("mode", "status", "code"),
    [
        ("maintenance", 503, "INSTANCE_MAINTENANCE"),
        ("recovery_only", 409, "INSTANCE_RECOVERY_ONLY"),
    ],
)
def test_instance_refuses_new_mutations_before_auth_or_domain_work(mode, status, code):
    cfg = Settings(app_env="test", runtime_admission_mode=mode)
    app = create_app(cfg)
    with TestClient(app) as client:
        assert client.get("/api/v1/status").json()["runtime_admission_mode"] == mode
        for path in (
            "/api/v1/auth/register",
            "/api/v1/projects",
            f"/api/v1/projects/{uuid4()}/final-film/render",
        ):
            response = client.post(path, headers={"X-Runtime-Admission-Mode": "normal"}, json={})
            assert response.status_code == status and response.json()["code"] == code
            assert response.json()["details"] == {"request_accepted": False}
        assert client.get("/api/v1/auth/csrf").status_code == 200
        assert client.post("/api/v1/auth/login", json={}).status_code == 422


def test_mode_is_validated_and_public_facts_never_contain_secrets():
    with pytest.raises(ValidationError):
        Settings(runtime_admission_mode="unknown-mode")
    cfg = Settings(app_env="test", session_secret="synthetic-recovery-test-secret")
    facts = process_facts(cfg, "api")
    assert facts["runtime_admission_mode"] == "normal" and facts["service"] == "api"
    assert cfg.session_secret not in str(facts)
    assert len(facts["mode_config_hash"]) == 64
