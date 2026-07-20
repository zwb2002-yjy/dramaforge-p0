"""Health endpoint contract tests."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_returns_200_with_expected_shape(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "api"
    assert "version" in body and body["version"]
    assert "env" in body and body["env"]


def test_health_is_stable_across_calls(client: TestClient) -> None:
    first = client.get("/health").json()
    second = client.get("/health").json()
    assert set(first.keys()) == set(second.keys())
    assert first["status"] == second["status"]
    assert first["service"] == second["service"]


def test_api_v1_status(client: TestClient) -> None:
    response = client.get("/api/v1/status")
    assert response.status_code == 200
    assert response.json()["api"] == "v1"
