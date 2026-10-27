"""Policy loaded in the pinned Proxy, not in the DramaForge application process."""

import asyncio

from fastapi import HTTPException
from fastapi.dependencies.utils import get_dependant
from litellm.integrations.custom_logger import CustomLogger
from starlette.requests import Request
from transport_policy import install_no_redirects

RESERVED = {
    "api_base", "base_url", "api_key", "custom_llm_provider", "client", "model_list",
    "silent_model", "specific_deployment", "extra_headers", "headers", "http_client",
    "async_client", "litellm_credential_name", "mock_response", "mock_testing_fallbacks",
    "mock_testing_context_fallbacks", "mock_testing_content_policy_fallbacks",
}


def reject_transport_overrides(body):
    if not isinstance(body, dict):
        raise HTTPException(422, "A Chat request object is required")
    if RESERVED.intersection(body):
        raise HTTPException(400, "Request-level transport overrides are forbidden")
    extra_body = body.get("extra_body")
    if isinstance(extra_body, dict) and (RESERVED | {"model"}).intersection(extra_body):
        raise HTTPException(400, "Request body cannot replace deployment identity")


def _install_creation_boundary():
    from litellm.proxy.proxy_server import app

    if getattr(app.state, "dramaforge_create_guard", False):
        return
    lock = asyncio.Lock()

    async def chat_boundary(request: Request):
        # Check the original body before Proxy sanitization can drop flags such
        # as mock_response. Never accept a hidden request to fake a model call.
        reject_transport_overrides(await request.json())

    async def unique_alias(request: Request):
        from litellm.proxy.proxy_server import llm_router

        async with lock:
            body = await request.json()
            if not isinstance(body, dict) or not isinstance(body.get("litellm_params"), dict):
                raise HTTPException(422, "A model deployment object is required")
            if body.get("litellm_params", {}).get("silent_model"):
                raise HTTPException(400, "Shadow model requests are forbidden")
            if any(entry.get("model_name") == body.get("model_name")
                   for entry in llm_router.model_list):
                raise HTTPException(409, "Model alias already exists")
            yield

    # The dependency runs after the endpoint's existing authorization. Its
    # generator holds the lock through DB write/router reload/response. This
    # pinned single-worker Proxy is the only model writer; no check/write race.
    for route in app.routes:
        if getattr(route, "path", None) == "/model/new" and hasattr(route, "dependant"):
            route.dependant.dependencies.append(get_dependant(path=route.path, call=unique_alias))
        if getattr(route, "path", None) in {
            "/chat/completions", "/v1/chat/completions", "/completions", "/v1/completions"
        } and hasattr(route, "dependant"):
            route.dependant.dependencies.append(get_dependant(path=route.path, call=chat_boundary))
    app.state.dramaforge_create_guard = True


def _pin_prisma_control_port():
    import os

    from prisma.engine import query

    # prisma-client-py 0.11 otherwise allocates a random localhost HTTP port.
    # One fixed control port avoids granting all loopback ephemeral ports.
    port = int(os.environ.get("LITELLM_PRISMA_ENGINE_PORT", "4001"))
    query.utils.get_open_port = lambda: port


class GatewayPolicy(CustomLogger):
    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        from litellm.proxy.proxy_server import llm_router

        model = data.get("model")
        deployments = [
            entry for entry in llm_router.model_list
            if entry.get("model_name") == model or entry.get("model_info", {}).get("id") == model
        ]
        if len(deployments) != 1:
            raise HTTPException(409, "A model reference must identify exactly one deployment")
        # Routing/credentials belong to the stored deployment, never a user's
        # Chat payload. extra_body is merged by upstream SDKs after model=.
        reject_transport_overrides(data)
        if deployments[0].get("litellm_params", {}).get("silent_model"):
            raise HTTPException(409, "Shadow model requests are forbidden")
        # Router request-level values dominate deployment defaults in this
        # locked version. Body/header overrides cannot re-enable unsafe replay.
        data["num_retries"] = 0
        data["max_retries"] = 0
        data["fallbacks"] = []
        data["context_window_fallbacks"] = []
        data["content_policy_fallbacks"] = []
        data["model_group_retry_policy"] = {}
        return data


install_no_redirects()
_pin_prisma_control_port()
_install_creation_boundary()
policy = GatewayPolicy()
