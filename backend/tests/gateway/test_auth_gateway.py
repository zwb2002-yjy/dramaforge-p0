"""Real pinned Nginx edge behavior; upstream responses are synthetic."""

import asyncio
import os

import httpx
import pytest


@pytest.mark.asyncio
async def test_auth_limit_uses_tcp_peer_recovers_and_isolates_remote_clients():
    gateway = os.environ["AUTH_GATEWAY_URL"]
    async with httpx.AsyncClient(trust_env=False, timeout=5) as client:
        responses = []
        for index in range(7):
            responses.append(
                await client.post(
                    f"{gateway}/api/v1/auth/login",
                    json={"password": "invalid"},
                    headers={"X-Forwarded-For": f"203.0.113.{index + 1}"},
                )
            )
        assert [response.status_code for response in responses] == [401] * 6 + [429]
        limited = responses[-1]
        assert limited.json()["code"] == "AUTH_RATE_LIMITED"
        assert limited.headers["retry-after"] == "12"
        assert limited.headers["cache-control"] == "no-store"
        # Neither forwarded header can change the untrusted TCP peer identity.
        forged = await client.post(
            f"{gateway}/api/v1/auth/register",
            json={"password": "synthetic-valid"},
            headers={"X-Forwarded-For": "198.51.100.1", "X-Real-IP": "198.51.100.2"},
        )
        assert forged.status_code == 429
        # A separate container opens its own TCP connection; the first client's
        # quota cannot block this remote address, even with the same account.
        second = await client.get("http://auth-upstream-quality:8000/second-client")
        assert second.json() == {"status": 401}
        assert (await client.get(f"{gateway}/health")).status_code == 200
        await asyncio.sleep(13)
        recovered = await client.post(
            f"{gateway}/api/v1/auth/login",
            json={"password": "synthetic-valid"},
        )
        assert recovered.status_code == 200
        assert recovered.json()["id"] == "synthetic-user"
