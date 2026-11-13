"""Retired provider-name credential writes must not claim to configure text."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient


@pytest.mark.parametrize("provider", ["text", "agnes"])
def test_provider_name_credential_surface_is_retired(client: TestClient, provider: str) -> None:
    workspace_id = uuid4()
    path = f"/api/v1/workspaces/{workspace_id}/provider-credentials"
    assert client.put(path, json={"provider": provider, "api_key": "unused"}).status_code == 404
    assert client.get(f"{path}/{provider}").status_code == 404
    from app.main import app

    paths = app.openapi()["paths"]
    assert not any("provider-credentials" in route for route in paths)
