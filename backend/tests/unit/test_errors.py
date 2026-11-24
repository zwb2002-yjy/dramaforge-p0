"""Problem Details error mapping tests."""

from __future__ import annotations

import httpx
import pytest
from app.api.errors import register_exception_handlers
from app.shared.errors import NotFoundError
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError


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


@pytest.mark.parametrize("error,expected", [
    (RuntimeError("connection configuration refused"), "INTERNAL_ERROR"),
    (httpx.ConnectError("upstream connection refused"), "INTERNAL_ERROR"),
    (OperationalError(None, None, Exception("database connection failed")), "DATABASE_UNAVAILABLE"),
])
def test_only_database_exception_types_are_reported_as_database_outages(error, expected):
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    async def boom():
        raise error

    response = TestClient(app, raise_server_exceptions=False).get("/boom")
    assert response.json()["code"] == expected
    assert response.status_code == (503 if expected == "DATABASE_UNAVAILABLE" else 500)
    assert "details" not in response.json()
    assert type(error).__name__ not in response.text
