"""Real locked Proxy + DB + kernel ACL + counted synthetic HTTP upstream."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest

MASTER = "sk-quality-policy-master-key"


@pytest.fixture(scope="module")
def proxy() -> httpx.Client:
    url = os.environ.get("LITELLM_POLICY_URL", "")
    if not url:
        if os.environ.get("LITELLM_INTEGRATION_REQUIRED") == "1":
            pytest.fail("LITELLM_POLICY_URL is required for the Proxy security gate")
        pytest.skip("dedicated Proxy security environment not configured")
    with httpx.Client(
        base_url=url, headers={"Authorization": f"Bearer {MASTER}"}, timeout=20, trust_env=False
    ) as client:
        yield client


def deployment(
    proxy: httpx.Client,
    scenario: str = "success",
    *,
    base: str | None = None,
    alias: str | None = None,
) -> tuple[str, str]:
    identifier = str(uuid.uuid4())
    name = alias or f"quality-{scenario}-{identifier}"
    response = proxy.post(
        "/model/new",
        json={
            "model_name": name,
            "litellm_params": {
                "model": f"openai/{identifier}",
                "api_key": "synthetic-key",
                "api_base": base or f"http://litellm-mock-quality:9000/{scenario}/v1",
                "timeout": 0.4,
                "max_retries": 2,
                "num_retries": 2,
            },
            "model_info": {"id": identifier},
        },
    )
    assert response.status_code == 200, response.text
    return name, identifier


def event_count(identifier: str) -> int:
    mock_url = os.environ["LITELLM_MOCK_URL"]
    response = httpx.get(f"{mock_url}/events", trust_env=False)
    response.raise_for_status()
    return sum(row["model"] == identifier for row in response.json())


def reject_count() -> int:
    rules = subprocess.run(["iptables-save", "-c"], check=True, capture_output=True, text=True)
    match = re.search(r"\[(\d+):\d+\] -A OUTPUT -j REJECT", rules.stdout)
    assert match is not None, "the dedicated namespace must have a final REJECT rule"
    return int(match.group(1))


@pytest.mark.parametrize("scenario", ["rate-limit", "unavailable", "disconnect", "timeout"])
def test_request_and_deployment_cannot_reenable_unknown_outcome_replay(
    proxy: httpx.Client, scenario: str
) -> None:
    alias, identifier = deployment(proxy, scenario)
    response = proxy.post(
        "/v1/chat/completions",
        headers={"x-litellm-num-retries": "2"},
        json={
            "model": alias,
            "messages": [{"role": "user", "content": "synthetic"}],
            "num_retries": 2,
            "max_retries": 2,
        },
    )
    assert response.status_code >= 400
    assert event_count(identifier) == 1


def test_same_origin_redirect_is_not_followed(proxy: httpx.Client) -> None:
    alias, identifier = deployment(proxy, "redirect")
    response = proxy.post(
        "/v1/chat/completions",
        json={
            "model": alias,
            "messages": [{"role": "user", "content": "synthetic"}],
        },
    )
    assert response.status_code >= 400
    assert event_count(identifier) == 1


@pytest.mark.parametrize(
    "base", ["http://litellm-mock-quality:9001/v1", "http://169.254.169.254/v1"]
)
def test_real_proxy_process_cannot_reach_ungranted_destinations(
    proxy: httpx.Client, base: str
) -> None:
    alias, identifier = deployment(proxy, base=base)
    before = reject_count()
    response = proxy.post(
        "/v1/chat/completions",
        json={
            "model": alias,
            "messages": [{"role": "user", "content": "synthetic"}],
        },
    )
    assert response.status_code >= 400
    assert event_count(identifier) == 0
    assert reject_count() > before, "failure must come from the kernel ACL, not a remote HTTP error"


def test_duplicate_alias_is_rejected_without_any_upstream_request(proxy: httpx.Client) -> None:
    alias, first = deployment(proxy)
    duplicate = proxy.post(
        "/model/new",
        json={
            "model_name": alias,
            "litellm_params": {"model": "openai/synthetic-duplicate"},
            "model_info": {"id": str(uuid.uuid4())},
        },
    )
    assert duplicate.status_code == 409
    response = proxy.post(
        "/v1/chat/completions",
        json={
            "model": alias,
            "messages": [{"role": "user", "content": "synthetic"}],
        },
    )
    assert response.status_code == 200
    assert event_count(first) == 1


@pytest.mark.parametrize(
    ("override", "expected_status"),
    [
        ({"api_base": "http://litellm-mock-quality:9000/other/v1"}, 401),
        ({"api_key": "synthetic-other-account"}, 400),
        ({"custom_llm_provider": "openai"}, 400),
        ({"extra_body": {"model": "another-model"}}, 400),
        ({"extra_headers": {"Authorization": "synthetic"}}, 400),
        ({"headers": {"Authorization": "synthetic"}}, 400),
        ({"extra_body": {"headers": {"Authorization": "synthetic"}}}, 400),
        ({"mock_response": "synthetic-bypass"}, 400),
    ],
)
def test_request_cannot_replace_frozen_deployment_transport(
    proxy: httpx.Client, override: dict[str, object], expected_status: int
) -> None:
    alias, identifier = deployment(proxy)
    response = proxy.post(
        "/v1/chat/completions",
        json={
            "model": alias,
            "messages": [{"role": "user", "content": "synthetic"}],
            **override,
        },
    )
    # This pinned Proxy rejects api_base at authentication before our hook.
    assert response.status_code == expected_status, response.text
    assert event_count(identifier) == 0


def test_model_create_cannot_enable_silent_shadow_requests(proxy: httpx.Client) -> None:
    alias, identifier = deployment(proxy)
    response = proxy.post(
        "/model/new",
        json={
            "model_name": str(uuid.uuid4()),
            "litellm_params": {"model": "openai/synthetic-shadow", "silent_model": alias},
            "model_info": {"id": str(uuid.uuid4())},
        },
    )
    assert response.status_code == 400, response.text
    assert event_count(identifier) == 0


def test_failed_deployment_cannot_route_to_request_fallback(proxy: httpx.Client) -> None:
    alias, identifier = deployment(proxy, "unavailable")
    other, other_id = deployment(proxy)
    response = proxy.post(
        "/v1/chat/completions",
        json={
            "model": alias,
            "messages": [{"role": "user", "content": "synthetic"}],
            "fallbacks": [{alias: [other]}],
            "num_retries": 2,
        },
    )
    assert response.status_code == 503
    assert event_count(identifier) == 1
    assert event_count(other_id) == 0


def test_yaml_alias_cannot_be_shadowed_by_a_db_model(proxy: httpx.Client) -> None:
    created = proxy.post(
        "/model/new",
        json={
            "model_name": "quality-legacy",
            "litellm_params": {"model": "openai/synthetic-new"},
            "model_info": {"id": str(uuid.uuid4())},
        },
    )
    assert created.status_code == 409
    result = proxy.post(
        "/v1/chat/completions",
        json={
            "model": "quality-legacy",
            "messages": [{"role": "user", "content": "synthetic"}],
        },
    )
    assert result.status_code == 200
    assert result.json()["choices"][0]["message"]["content"] == "historical-alias"


def test_concurrent_creation_cannot_race_into_duplicate_aliases(proxy: httpx.Client) -> None:
    alias = "quality-race-" + str(uuid.uuid4())

    def create(_: int) -> int:
        response = proxy.post(
            "/model/new",
            json={
                "model_name": alias,
                "litellm_params": {"model": "openai/synthetic-race"},
                "model_info": {"id": str(uuid.uuid4())},
            },
        )
        return response.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(create, range(2)))
    assert sorted(statuses) == [200, 409]


@pytest.mark.asyncio
async def test_requests_and_aiohttp_cannot_follow_same_origin_redirect() -> None:
    import importlib.util

    import aiohttp
    import requests

    path = Path(__file__).resolve().parents[3] / "infra/litellm/transport_policy.py"
    spec = importlib.util.spec_from_file_location("gateway_transport_contract", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.install_no_redirects()
    target = os.environ["LITELLM_MOCK_URL"] + "/redirect/v1/chat/completions"
    identifier = str(uuid.uuid4())
    response = requests.post(target, json={"model": identifier}, timeout=3, allow_redirects=True)
    assert response.status_code == 307
    assert event_count(identifier) == 1
    identifier = str(uuid.uuid4())
    async with (
        aiohttp.ClientSession(trust_env=False) as client,
        client.post(target, json={"model": identifier}, allow_redirects=True) as result,
    ):
        assert result.status == 307
    assert event_count(identifier) == 1


def test_data_key_cannot_manage_models_or_cross_model_scope(proxy: httpx.Client) -> None:
    alias, _ = deployment(proxy)
    other, _ = deployment(proxy)
    created = proxy.post("/key/generate", json={"models": [alias], "key_type": "llm_api"})
    assert created.status_code == 200
    headers = {"Authorization": f"Bearer {created.json()['key']}"}
    assert (
        proxy.post("/model/delete", json={"id": str(uuid.uuid4())}, headers=headers).status_code
        == 403
    )
    assert (
        proxy.post(
            "/v1/chat/completions",
            json={
                "model": other,
                "messages": [{"role": "user", "content": "synthetic"}],
            },
            headers=headers,
        ).status_code
        == 403
    )
    result = proxy.post(
        "/v1/chat/completions",
        json={
            "model": alias,
            "messages": [{"role": "user", "content": "synthetic"}],
        },
        headers=headers,
    )
    assert result.status_code == 200, result.text


def test_managed_reference_cannot_change_target_and_stale_key_revision_is_rejected(
    proxy: httpx.Client,
) -> None:
    identifier, workspace, connection = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    alias = "df-" + uuid.UUID(identifier).hex
    params = {
        "model": f"openai/{identifier}",
        "api_base": "http://litellm-mock-quality:9000/success/v1",
        "api_key": "synthetic-managed-key",
        "max_retries": 0,
    }
    config_hash = hashlib.sha256(
        json.dumps(
            {"model": params["model"], "api_base": params["api_base"]},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    info = {
        "id": identifier,
        "df_managed": True,
        "df_workspace_id": workspace,
        "df_connection_id": connection,
        "df_config_hash": config_hash,
        "df_key_revision": 1,
        "df_request_id": str(uuid.uuid4()),
        "df_contract_profile": "chat_text_v1",
    }
    created = proxy.post(
        "/model/new", json={"model_name": alias, "litellm_params": params, "model_info": info}
    )
    assert created.status_code == 200, created.text
    frozen = {
        "deployment_id": identifier,
        "workspace_id": workspace,
        "connection_id": connection,
        "config_hash": config_hash,
        "key_revision": 1,
    }
    payload = {
        "model": alias,
        "messages": [{"role": "user", "content": "synthetic"}],
        "metadata": {"dramaforge_execution": frozen},
    }
    assert proxy.post("/v1/chat/completions", json=payload).status_code == 200
    for change in (
        {"model": "openai/another-weight"},
        {"api_base": "http://litellm-mock-quality:9000/other/v1"},
    ):
        result = proxy.post(
            "/model/update", json={"model_info": {"id": identifier}, "litellm_params": change}
        )
        assert result.status_code == 409
    assert (
        proxy.patch(
            f"/model/{identifier}/update", json={"litellm_params": {"model": "openai/other"}}
        ).status_code
        == 409
    )
    assert proxy.post("/model/delete", json={"id": identifier}).status_code == 409
    invalid = {
        **payload,
        "metadata": {"dramaforge_execution": {**frozen, "workspace_id": str(uuid.uuid4())}},
    }
    assert proxy.post("/v1/chat/completions", json=invalid).status_code == 409
    assert event_count(identifier) == 1
    rotated = proxy.patch(
        f"/model/{identifier}/update",
        json={
            "model_info": {
                "id": identifier,
                "df_key_revision": 2,
                "df_request_id": str(uuid.uuid4()),
            },
            "litellm_params": {"api_key": "synthetic-key-two"},
        },
    )
    assert rotated.status_code == 200, rotated.text
    assert proxy.post("/v1/chat/completions", json=payload).status_code == 409
    assert event_count(identifier) == 1
    payload["metadata"]["dramaforge_execution"] = {**frozen, "key_revision": 2}
    result = proxy.post("/v1/chat/completions", json=payload)
    assert result.status_code == 200, result.text
    assert event_count(identifier) == 2


def test_bootstrap_uses_scoped_keys_without_secret_output_and_is_idempotent(
    proxy: httpx.Client,
) -> None:
    import sys

    script = Path(__file__).resolve().parents[3] / "infra/litellm/bootstrap_keys.py"
    data_key, admin_key = "sk-quality-bootstrap-data-key", "sk-quality-bootstrap-model-admin-key-v4"
    env = {
        **os.environ,
        "LITELLM_MASTER_KEY": MASTER,
        "LITELLM_API_KEY": data_key,
        "LITELLM_MODEL_ADMIN_KEY": admin_key,
        "LITELLM_BOOTSTRAP_PROXY_URL": str(proxy.base_url).rstrip("/"),
    }
    for _ in range(2):
        completed = subprocess.run(
            [sys.executable, str(script)], env=env, capture_output=True, text=True, check=True
        )
        assert data_key not in completed.stdout + completed.stderr
        assert admin_key not in completed.stdout + completed.stderr
    admin_headers = {"Authorization": "Bearer " + admin_key}
    data_headers = {"Authorization": "Bearer " + data_key}
    assert proxy.get("/model/info", headers=admin_headers).status_code == 200
    assert (
        proxy.post("/key/generate", json={"models": []}, headers=admin_headers).status_code == 403
    )
    assert proxy.get("/v1/models", headers=data_headers).status_code == 200
    _, identifier = deployment(proxy)
    updated = proxy.patch(
        f"/model/{identifier}/update",
        json={
            "model_info": {"id": identifier},
            "litellm_params": {"api_key": "synthetic-scoped-update"},
        },
        headers=admin_headers,
    )
    assert updated.status_code == 200, updated.text
    assert (
        proxy.post(
            "/model/new",
            json={"model_name": "denied", "litellm_params": {"model": "openai/denied"}},
            headers=data_headers,
        ).status_code
        == 403
    )


def test_legacy_patch_cannot_promote_or_collide_with_reserved_managed_identity(
    proxy: httpx.Client,
) -> None:
    _, identifier = deployment(proxy)
    for body in (
        {"model_name": "df-" + uuid.uuid4().hex},
        {"model_info": {"id": identifier, "df_managed": True}},
    ):
        response = proxy.patch(f"/model/{identifier}/update", json=body)
        assert response.status_code == 409
    other, other_id = deployment(proxy)
    response = proxy.patch(f"/model/{identifier}/update", json={"model_name": other})
    assert response.status_code == 409
    assert event_count(identifier) == event_count(other_id) == 0
