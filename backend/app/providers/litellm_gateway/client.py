"""LiteLLM Gateway HTTP client + classified errors (spec §66–§70, F4–F7).

Separation of concerns (spec §67): the :class:`LiteLLMGatewayClient` owns ALL
HTTP to the official LiteLLM Proxy (URL join, auth header, single-attempt POST,
classification, model discovery cache); the V3 :class:`LiteLLMModelAdapter`
only does semantic mapping (TextGenerateRequest → OpenAI-compatible payload →
ProviderCreateResult). The adapter never opens an httpx session itself.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.providers.errors import SubmissionOutcomeUnknownError
from app.providers.litellm_gateway.errors import (
    classify_http,
    gateway_unavailable,
)
from app.providers.litellm_gateway.metadata import (
    parse_allowlisted_headers,
)

# LiteLLM Router owns provider/deployment retry/fallback/cooldown (spec §5).
# DramaForge does ONE POST per create — no blind client retry (spec §95/§96).
DEFAULT_TIMEOUT_S = 120.0
SHORT_TIMEOUT_S = 10.0
MODELS_CACHE_TTL_S = 300.0

# Canonical OpenAI-compatible path the proxy exposes (spec §19/§20/§21).
_CHAT_SUFFIXES = ("/v1/chat/completions", "/chat/completions")
_MODELS_SUFFIXES = ("/v1/models", "/models")


class GatewayModel(BaseModel):
    """One logical model exposed by ``GET /v1/models`` (spec §69)."""

    id: str
    object: str = "model"


class GatewayResponse(BaseModel):
    """Normalized successful gateway response (spec §70).

    ``metadata`` carries only the allowlisted cost/retry/fallback/latency/
    identity headers — never authorization material (spec §48/§121).
    """

    status_code: int
    data: dict[str, Any]
    request_id: str | None = None
    response_cost: Decimal | None = None
    attempted_retries: int | None = None
    attempted_fallbacks: int | None = None
    latency_ms: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


def normalize_chat_url(base_url: str) -> str:
    """Return the canonical ``/v1/chat/completions`` endpoint for a gateway base
    URL. Accepts an already-full endpoint or a ``/v1``-suffixed base so the repo
    never mixes path conventions (spec §20/§21)."""
    base = base_url.rstrip("/")
    for suffix in _CHAT_SUFFIXES:
        if base.endswith(suffix):
            return base
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def normalize_models_url(base_url: str) -> str:
    """Canonical ``/v1/models`` discovery endpoint (spec §35)."""
    base = base_url.rstrip("/")
    for suffix in _MODELS_SUFFIXES:
        if base.endswith(suffix):
            return base
    if base.endswith("/v1"):
        return f"{base}/models"
    return f"{base}/v1/models"


class LiteLLMGatewayClient:
    """HTTP client for the official LiteLLM Proxy (spec §66/§69).

    ``transport`` is injected only by tests (httpx MockTransport); production
    uses real sockets with ``trust_env=False`` so the internal
    DramaForge→Gateway hop never leaks through a host HTTP proxy (spec §27).
    """

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_s: float | None = None,
    ) -> None:
        self._settings_override = settings
        self._transport = transport
        self._timeout_s = timeout_s or DEFAULT_TIMEOUT_S
        self._models_cache: tuple[float, list[str]] | None = None

    @property
    def _settings(self) -> Settings:
        # Read lazily so tests can flip env vars + clear the settings cache.
        return self._settings_override or get_settings()

    def _base_url(self) -> str:
        return self._settings.litellm_gateway_url.strip().rstrip("/")

    # ------------------------------------------------------------------
    # URLs / headers
    # ------------------------------------------------------------------

    def chat_url(self) -> str:
        return normalize_chat_url(self._base_url())

    def models_url(self) -> str:
        return normalize_models_url(self._base_url())

    def liveliness_url(self) -> str:
        return f"{self._base_url()}/health/liveliness"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        key = self._settings.litellm_api_key.strip()
        if key:
            headers["Authorization"] = f"Bearer {key}"
        return headers

    def _client(self, timeout_s: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=timeout_s,
            transport=self._transport,
            proxy=None,
            trust_env=False,
        )

    # ------------------------------------------------------------------
    # read-only surfaces
    # ------------------------------------------------------------------

    async def readiness(self) -> bool:
        """Liveliness probe. Never raises — callers surface ``unavailable``."""
        try:
            async with self._client(SHORT_TIMEOUT_S) as client:
                resp = await client.get(self.liveliness_url(), headers=self._headers())
            return resp.status_code < 400
        except httpx.HTTPError:
            return False

    async def list_models(self, *, force: bool = False) -> list[str]:
        """Logical aliases from ``GET /v1/models`` with a TTL cache (spec §36).

        Discovery is never per-request: the cache is refreshed only after
        ``MODELS_CACHE_TTL_S`` or an explicit ``force=True`` refresh.
        """
        now = _utc_now()
        if (
            not force
            and self._models_cache is not None
            and now - self._models_cache[0] < MODELS_CACHE_TTL_S
        ):
            return list(self._models_cache[1])
        try:
            async with self._client(SHORT_TIMEOUT_S) as client:
                resp = await client.get(self.models_url(), headers=self._headers())
        except httpx.HTTPError as exc:
            raise gateway_unavailable(
                f"cannot reach LiteLLM gateway {self._base_url() or '(unset)'}: {exc}"
            ) from exc
        if resp.status_code >= 400:
            raise classify_http(resp.status_code, _error_message(resp))
        data = _json_body(resp)
        rows = data.get("data") if isinstance(data, dict) else None
        ids: list[str] = []
        for row in rows or []:
            if isinstance(row, dict) and isinstance(row.get("id"), str) and row["id"]:
                ids.append(row["id"])
        self._models_cache = (now, ids)
        return ids

    # ------------------------------------------------------------------
    # create surface
    # ------------------------------------------------------------------

    async def chat_completion(
        self,
        *,
        model: str,
        payload: dict[str, Any],
        extra_headers: dict[str, str] | None = None,
    ) -> GatewayResponse:
        """ONE POST to ``/v1/chat/completions`` (spec §5/§95). No blind retry.

        Failure classification (spec §63–§65):
        - connect/connect-timeout before send       → gateway unavailable
        - read/write timeout or dropped connection  → :class:`SubmissionOutcomeUnknownError`
        - HTTP error (401/403/404/429/5xx, ...)     → :class:`ProviderError` via ``classify_http``
        """
        body = {**payload, "model": model}
        headers = {**self._headers(), **(extra_headers or {})}
        try:
            async with self._client(self._timeout_s) as client:
                resp = await client.post(self.chat_url(), headers=headers, json=body)
        except httpx.ConnectTimeout as exc:
            raise gateway_unavailable(
                f"connect timeout to LiteLLM gateway {self._base_url()}: {exc}"
            ) from exc
        except httpx.ConnectError as exc:
            raise gateway_unavailable(
                f"cannot connect to LiteLLM gateway {self._base_url()}: {exc}"
            ) from exc
        except httpx.PoolTimeout as exc:
            raise gateway_unavailable(
                f"connection pool timeout to LiteLLM gateway: {exc}"
            ) from exc
        except httpx.ReadTimeout as exc:
            # The request left this process; the gateway/provider may have
            # accepted and billed it. Never auto re-POST (spec §64/§65).
            raise SubmissionOutcomeUnknownError(
                f"LiteLLM read timeout after submit: {exc}"
            ) from exc
        except httpx.WriteTimeout as exc:
            raise SubmissionOutcomeUnknownError(
                f"LiteLLM write timeout after submit: {exc}"
            ) from exc
        except httpx.RemoteProtocolError as exc:
            raise SubmissionOutcomeUnknownError(
                f"LiteLLM connection closed after submit: {exc}"
            ) from exc
        except httpx.NetworkError as exc:
            raise gateway_unavailable(
                f"network error reaching LiteLLM gateway: {exc}"
            ) from exc
        if resp.status_code >= 400:
            raise classify_http(resp.status_code, _error_message(resp))
        data = _json_body(resp)
        metadata = parse_allowlisted_headers(resp.headers)
        return GatewayResponse(
            status_code=resp.status_code,
            data=data,
            metadata=metadata,
            request_id=metadata.get("request_id"),
            response_cost=metadata.get("litellm_response_cost")
            or metadata.get("litellm_response_cost_original"),
            attempted_retries=metadata.get("litellm_attempted_retries"),
            attempted_fallbacks=metadata.get("litellm_attempted_fallbacks"),
            latency_ms=metadata.get("litellm_response_duration_ms"),
        )


def _utc_now() -> float:
    return datetime.now(UTC).timestamp()


def _json_body(resp: httpx.Response) -> dict[str, Any]:
    try:
        data = resp.json()
    except ValueError:
        data = {"raw_status": resp.status_code, "text": resp.text[:200]}
    return data if isinstance(data, dict) else {"raw_status": resp.status_code}


def _error_message(resp: httpx.Response) -> str:
    data = _json_body(resp)
    error = data.get("error") if isinstance(data, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or data.get("message") or "")[:400]
    return str(data.get("message") or "")[:400]
