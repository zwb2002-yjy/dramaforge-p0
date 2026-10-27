"""Real locked Proxy + DB + kernel ACL + counted synthetic HTTP upstream."""

from __future__ import annotations

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
