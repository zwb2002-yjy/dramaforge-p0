"""Problem Details error mapping tests."""

from __future__ import annotations

from app.api.errors import register_exception_handlers
from app.shared.errors import NotFoundError
from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_app_error_maps_to_problem_details() -> None:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    async def boom() -> None:
        raise NotFoundError("missing thing")

    client = TestClient(app)
    response = client.get("/boom")
    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "NOT_FOUND"
    assert body["detail"] == "missing thing"
    assert body["status"] == 404
