"""FastAPI application entrypoint."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.api.errors import register_exception_handlers
from app.api.v1.router import api_router
from app.config import Settings, get_settings
from app.events.sse import RedisSseBridge
from app.shared.db import get_session
from app.shared.observability import REQUESTS_TOTAL, metrics_payload


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # BOOT-0: /health remains usable without DB/Redis, while production facts
    # are bridged into this API process when Redis is available.
    cfg = getattr(app.state, "settings", get_settings())
    bridge = None if cfg.app_env == "test" else RedisSseBridge(cfg.redis_url)
    bridge_task = asyncio.create_task(bridge.run_forever()) if bridge else None
    try:
        yield
    finally:
        if bridge_task is not None:
            bridge_task.cancel()
            await asyncio.gather(bridge_task, return_exceptions=True)
        if bridge is not None:
            await bridge.close()
        from app.runtime.resources import close_runtime_resources

        await close_runtime_resources()


def _metric_path(request: Request, api_prefix: str) -> str:
    """Return the matched route template, never a raw path with identifiers."""
    route = request.scope.get("route")
    template = getattr(route, "path", None)
    if not isinstance(template, str):
        return "unmatched"
    prefix = api_prefix.rstrip("/")
    raw = request.scope.get("path", "")
    if (
        prefix
        and isinstance(raw, str)
        and raw.startswith(prefix + "/")
        and not template.startswith(prefix + "/")
    ):
        return prefix + template
    return template


def create_app(settings: Settings | None = None) -> FastAPI:
    """Application factory used by uvicorn and tests."""
    cfg = settings or get_settings()
    app = FastAPI(
        title=cfg.app_name,
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs" if cfg.app_env != "production" else None,
        redoc_url=None,
    )
    app.state.settings = cfg

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_exception_handlers(app)

    @app.middleware("http")
    async def count_http_requests(request: Request, call_next: Any) -> Response:
        """Count every handled request under its bounded route template."""
        try:
            response: Response = await call_next(request)
        except Exception:
            REQUESTS_TOTAL.labels(
                method=request.method,
                path=_metric_path(request, cfg.api_prefix),
                status="500",
            ).inc()
            raise
        REQUESTS_TOTAL.labels(
            method=request.method,
            path=_metric_path(request, cfg.api_prefix),
            status=str(response.status_code),
        ).inc()
        return response

    app.include_router(api_router, prefix=cfg.api_prefix)

    @app.get("/health", tags=["system"])
    async def health(
        session: AsyncSession = Depends(get_session),  # noqa: B008
    ) -> Any:
        """Liveness + DB readiness. 503 when PostgreSQL unreachable (UI shows 离线)."""
        from fastapi.responses import JSONResponse

        db_ok = False
        migration_head: str | None = None
        try:
            await session.execute(text("SELECT 1"))
            db_ok = True
            # Readiness must distinguish a reachable-but-unmigrated database
            # from the exact schema the candidate build expects.
            migration_head = (
                await session.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one_or_none()
        except Exception:  # noqa: BLE001 — surface readiness only
            pass

        body: dict[str, Any] = {
            "status": "ok" if db_ok else "degraded",
            "service": "api",
            "version": __version__,
            "env": cfg.app_env,
            "db": "up" if db_ok else "down",
            "migration_head": migration_head,
            "source_commit": cfg.source_commit,
            "dependencies": {
                "litellm": await _litellm_dependency_status(cfg),
            },
        }
        if db_ok:
            return body
        return JSONResponse(status_code=503, content=body)

    @app.get("/metrics", tags=["system"])
    async def metrics() -> Response:
        return PlainTextResponse(
            content=metrics_payload().decode("utf-8"),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    return app


async def _litellm_dependency_status(cfg: Settings) -> dict[str, str]:
    """LiteLLM availability is advisory — never makes the API unhealthy (fix
    spec §77/§122). Unset URL fails fast; a configured-but-down gateway is
    reported as ``unavailable`` while local/media models stay usable."""
    if not cfg.litellm_gateway_url.strip():
        return {"status": "unavailable"}
    from app.providers.litellm_gateway.client import LiteLLMGatewayClient

    client = LiteLLMGatewayClient(settings=cfg, timeout_s=2.0)
    try:
        return {"status": "up" if await client.readiness() else "unavailable"}
    except Exception:  # noqa: BLE001 - readiness never raises by contract
        return {"status": "unavailable"}


app = create_app()
