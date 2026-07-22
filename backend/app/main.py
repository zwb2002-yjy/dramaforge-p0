"""FastAPI application entrypoint."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.api.errors import register_exception_handlers
from app.api.v1.router import api_router
from app.config import Settings, get_settings
from app.shared.db import get_session
from app.shared.observability import REQUESTS_TOTAL, metrics_payload


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # BOOT-0: no DB/Redis startup required for /health.
    yield


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

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_exception_handlers(app)
    app.include_router(api_router, prefix=cfg.api_prefix)

    @app.get("/health", tags=["system"])
    async def health(
        session: AsyncSession = Depends(get_session),  # noqa: B008
    ) -> Any:
        """Liveness + DB readiness. 503 when PostgreSQL unreachable (UI shows 离线)."""
        from fastapi.responses import JSONResponse

        db_ok = False
        db_error: str | None = None
        try:
            await session.execute(text("SELECT 1"))
            db_ok = True
        except Exception as exc:  # noqa: BLE001 — surface readiness only
            db_error = type(exc).__name__

        body: dict[str, Any] = {
            "status": "ok" if db_ok else "degraded",
            "service": "api",
            "version": __version__,
            "env": cfg.app_env,
            "db": "up" if db_ok else "down",
            "source_commit": cfg.source_commit,
        }
        if db_error:
            body["db_error"] = db_error
        if db_ok:
            REQUESTS_TOTAL.labels(method="GET", path="/health", status="200").inc()
            return body
        REQUESTS_TOTAL.labels(method="GET", path="/health", status="503").inc()
        return JSONResponse(status_code=503, content=body)

    @app.get("/metrics", tags=["system"])
    async def metrics() -> Response:
        return PlainTextResponse(
            content=metrics_payload().decode("utf-8"),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    return app


app = create_app()
