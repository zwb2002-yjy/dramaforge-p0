"""HTTP request metrics cover every handled request under bounded labels."""

from __future__ import annotations

from app.shared.observability import metrics_payload
from fastapi.testclient import TestClient


def test_request_metric_uses_route_templates_not_raw_paths(bare_client: TestClient) -> None:
    bare_client.get("/api/v1/auth/csrf")
    project_id = "00000000-0000-4000-8000-000000000000"
    bare_client.get(f"/api/v1/projects/{project_id}")

    payload = metrics_payload().decode("utf-8")

    assert 'path="/api/v1/auth/csrf"' in payload
    assert 'path="/api/v1/projects/{project_id}"' in payload
    assert project_id not in payload


def test_unmatched_requests_share_one_bounded_label(bare_client: TestClient) -> None:
    bare_client.get("/definitely-not-a-route")

    payload = metrics_payload().decode("utf-8")

    assert 'path="unmatched"' in payload
    assert "/definitely-not-a-route" not in payload
