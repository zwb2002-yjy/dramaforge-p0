"""FastAPI application entrypoint."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, Response

from app import __version__
from app.api.errors import register_exception_handlers
from app.api.v1.router import api_router
from app.config import Settings, get_settings
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
    async def health() -> dict[str, Any]:
        REQUESTS_TOTAL.labels(method="GET", path="/health", status="200").inc()
        return {
            "status": "ok",
            "service": "api",
            "version": __version__,
            "env": cfg.app_env,
        }

    @app.get("/metrics", tags=["system"])
    async def metrics() -> Response:
        return PlainTextResponse(
            content=metrics_payload().decode("utf-8"),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    return app


app = create_app()
