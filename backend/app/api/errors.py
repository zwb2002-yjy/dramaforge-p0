"""Map domain errors to RFC 7807-style Problem Details responses."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.shared.errors import AppError


def problem_response(
    *,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": f"https://dramaforge.local/errors/{code.lower()}",
        "title": code,
        "status": status_code,
        "detail": message,
        "code": code,
    }
    if details:
        body["details"] = details
    return JSONResponse(status_code=status_code, content=body)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
        return problem_response(
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            details=exc.details,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return problem_response(
            status_code=422,
            code="VALIDATION_ERROR",
            message="Request validation failed",
            details={"errors": exc.errors()},
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_handler(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "HTTP_ERROR"
        if exc.status_code == 404:
            code = "NOT_FOUND"
        elif exc.status_code == 401:
            code = "UNAUTHORIZED"
        elif exc.status_code == 403:
            code = "FORBIDDEN"
        detail = exc.detail if isinstance(exc.detail, str) else "HTTP error"
        return problem_response(status_code=exc.status_code, code=code, message=detail)

    @app.exception_handler(Exception)
    async def unhandled(_request: Request, exc: Exception) -> JSONResponse:
        """Map infrastructure failures to actionable Problem Details (not bare 500)."""
        name = type(exc).__name__
        msg = str(exc)
        if "Connect" in name or "connection" in msg.lower() or "refused" in msg.lower():
            return problem_response(
                status_code=503,
                code="DATABASE_UNAVAILABLE",
                message="数据库不可用（PostgreSQL 连接失败）。请启动 WSL Postgres 后重试。",
                details={"error_type": name},
            )
        # sqlalchemy wraps asyncpg errors
        if "OperationalError" in name or "InterfaceError" in name:
            return problem_response(
                status_code=503,
                code="DATABASE_UNAVAILABLE",
                message="数据库暂时不可用，请确认 PostgreSQL 已启动。",
                details={"error_type": name},
            )
        return problem_response(
            status_code=500,
            code="INTERNAL_ERROR",
            message=f"服务器错误: {name}",
            details={"error_type": name},
        )
