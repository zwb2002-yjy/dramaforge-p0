"""Authenticated HTTP diagnostics do not add a second execution writer."""

from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient
from tests.unit.test_workbench_api import _csrf, _project_id, _register, api

__all__ = ["api"]


def test_model_capability_http_scope_and_catalog_contract(api: tuple[TestClient, Any]) -> None:
    client, _factory = api
    _register(client)
    project_id = _project_id(client)
    response = client.get(
        f"/api/v1/projects/{project_id}/model-capabilities", params={"model_id": "minimax/image-01"}
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["selection"] == "explicit_catalog"
    assert data["report"]["account_status"] == "not_checked"
    assert (
        data["report"]["capabilities"]["image.edit"]["input_slots"]["reference_image"]["maximum"]
        == 1
    )
    assert (
        client.get(
            f"/api/v1/projects/{uuid4()}/model-capabilities",
            params={"model_id": "minimax/image-01"},
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/v1/projects/{project_id}/model-capabilities", params={"model_id": "nonexistent"}
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/v1/projects/{project_id}/model-capabilities",
            params={"model_id": "minimax/image-01", "stage": "video"},
        ).status_code
        == 422
    )


def test_compile_preview_forbids_model_supplied_approval_and_extra_options(
    api: tuple[TestClient, Any],
) -> None:
    client, _factory = api
    _register(client)
    project_id = _project_id(client)
    url = f"/api/v1/projects/{project_id}/shots/{uuid4()}/compile-preview"
    body = {
        "stage": "video",
        "prompt": "test",
        "mode_id": "explicit_binding",
        "expected_shot_version": 1,
        "accept_approximations": True,
    }
    response = client.post(url, json=body, headers={"X-CSRF-Token": _csrf(client)})
    assert response.status_code == 422, response.text
    body.update({"accept_approximations": False, "native_options": {"secret": "x"}})
    assert client.post(url, json=body, headers={"X-CSRF-Token": _csrf(client)}).status_code == 422
