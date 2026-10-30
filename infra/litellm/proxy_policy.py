"""Policy loaded in the pinned Proxy, not in the DramaForge application process."""

import asyncio
import hashlib
import json
from uuid import UUID

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


def _physical_hash(params):
    body = {"api_base": params["api_base"].rstrip("/"), "model": params["model"]}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _deployment(model):
    from litellm.proxy.proxy_server import llm_router

    entries = [entry for entry in llm_router.model_list if entry.get("model_name") == model
               or entry.get("model_info", {}).get("id") == model]
    if len(entries) != 1:
        raise HTTPException(409, "A model reference must identify exactly one deployment")
    return entries[0]


def _validate_managed_create(body):
    info, params = body.get("model_info", {}), body.get("litellm_params", {})
    if not isinstance(info, dict):
        raise HTTPException(422, "Model identity metadata must be an object")
    if not info.get("df_managed"):
        if str(body.get("model_name", "")).startswith("df-") or any(str(key).startswith("df_") for key in info):
            raise HTTPException(400, "Reserved deployment namespace requires managed identity")
        return
    try:
        identifier = UUID(info["id"])
        UUID(info["df_workspace_id"])
        UUID(info["df_connection_id"])
        UUID(info["df_request_id"])
        valid = (body.get("model_name") == f"df-{identifier.hex}"
                 and info.get("df_managed") is True
                 and info.get("df_key_revision") == 1
                 and info.get("df_contract_profile") == "chat_text_v1"
                 and info.get("df_config_hash") == _physical_hash(params)
                 and params["model"].startswith("openai/")
                 and not set(params).difference({"model", "api_base", "api_key", "max_retries"}))
    except (KeyError, ValueError, TypeError, AttributeError):
        valid = False
    if not valid:
        raise HTTPException(400, "Invalid managed deployment identity or unsupported protocol options")


def _install_creation_boundary():
    from litellm.proxy.proxy_server import app

    if getattr(app.state, "dramaforge_create_guard", False):
        return
    lock = asyncio.Lock()
    model_locks = {}

    def model_lock(identifier):
        return model_locks.setdefault(identifier, asyncio.Lock())

    async def chat_boundary(request: Request):
        # Check the original body before Proxy sanitization can drop flags such
        # as mock_response. Never accept a hidden request to fake a model call.
        body = await request.json()
        reject_transport_overrides(body)
        entry = _deployment(body.get("model"))
        identifier = entry.get("model_info", {}).get("id")
        async with model_lock(identifier):
            entry = _deployment(identifier)
            info = entry.get("model_info", {})
            if not info.get("df_managed"):
                import hmac
                import os
                # Retained aliases require a separately held trusted recovery
                # context. Ordinary generation keys only execute managed refs.
                bearer = request.headers.get("authorization", "").removeprefix("Bearer ")
                if not hmac.compare_digest(bearer, os.environ.get("LITELLM_MASTER_KEY", "")):
                    raise HTTPException(409, "Legacy model requires an explicit managed migration")
            if info.get("df_managed"):
                metadata = body.get("metadata", {})
                if not isinstance(metadata, dict) or not isinstance(metadata.get("dramaforge_execution", {}), dict):
                    raise HTTPException(400, "Execution metadata must be an object")
                expected = metadata.get("dramaforge_execution", {})
                valid = (expected.get("deployment_id") == identifier
                         and expected.get("workspace_id") == info.get("df_workspace_id")
                         and expected.get("connection_id") == info.get("df_connection_id")
                         and expected.get("config_hash") == info.get("df_config_hash")
                         and expected.get("key_revision") == info.get("df_key_revision")
                         and _physical_hash(entry["litellm_params"]) == info.get("df_config_hash"))
                if not valid:
                    raise HTTPException(409, "Frozen deployment reference no longer matches")
            # Keep the chosen credential/config stable through the whole HTTP
            # response, including streaming. Key rotation acquires this lock.
            yield

    async def model_mutation(request: Request):
        body = await request.json()
        if not isinstance(body, dict) or (body.get("model_info") is not None and not isinstance(body["model_info"], dict)):
            raise HTTPException(422, "Model update must contain object metadata")
        supplied_info = body.get("model_info") or {}
        identifier = (request.path_params.get("model_id") or body.get("id")
                      or supplied_info.get("id"))
        async with lock, model_lock(identifier):
            entry = _deployment(identifier)
            info = entry.get("model_info", {})
            if info.get("df_managed"):
                if request.method != "PATCH" or not request.path_params.get("model_id"):
                    raise HTTPException(409, "Managed versions are retained; create a replacement version")
                new_info = supplied_info
                try:
                    UUID(new_info["df_request_id"])
                    valid = (set(body) <= {"model_info", "litellm_params"}
                             and new_info.get("id") == identifier
                             and set(body.get("litellm_params", {})) == {"api_key"}
                             and set(new_info) == {"id", "df_key_revision", "df_request_id"}
                             and new_info["df_key_revision"] == info["df_key_revision"] + 1
                             and new_info["df_request_id"] != info["df_request_id"])
                except (KeyError, ValueError, TypeError):
                    valid = False
                if not valid:
                    raise HTTPException(409, "Only a new credential revision may update a managed version")
            else:
                new_info = supplied_info
                new_name = body.get("model_name")
                if (str(new_name or "").startswith("df-")
                        or any(str(key).startswith("df_") for key in new_info)
                        or (new_info.get("id") is not None and new_info["id"] != identifier)):
                    raise HTTPException(409, "Legacy models require a new managed version, not promotion")
                if new_name and new_name != entry.get("model_name"):
                    from litellm.proxy.proxy_server import llm_router
                    if any(candidate.get("model_name") == new_name for candidate in llm_router.model_list):
                        raise HTTPException(409, "Model alias already exists")
            yield

    async def unique_alias(request: Request):
        from litellm.proxy.proxy_server import llm_router

        async with lock:
            body = await request.json()
            if not isinstance(body, dict) or not isinstance(body.get("litellm_params"), dict):
                raise HTTPException(422, "A model deployment object is required")
            if body.get("litellm_params", {}).get("silent_model"):
                raise HTTPException(400, "Shadow model requests are forbidden")
            _validate_managed_create(body)
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
        if getattr(route, "path", None) in {
            "/model/update", "/model/delete", "/model/{model_id}/update"
        } and hasattr(route, "dependant"):
            route.dependant.dependencies.append(get_dependant(path=route.path, call=model_mutation))
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
