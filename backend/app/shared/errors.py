"""Domain-level exceptions with stable error codes."""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base application error mapped to Problem Details by the API layer."""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


class NotFoundError(AppError):
    def __init__(self, message: str = "Resource not found", **kwargs: Any) -> None:
        super().__init__(code="NOT_FOUND", message=message, status_code=404, **kwargs)


class ValidationAppError(AppError):
    def __init__(self, message: str = "Validation failed", **kwargs: Any) -> None:
        super().__init__(code="VALIDATION_ERROR", message=message, status_code=422, **kwargs)


class UnauthorizedError(AppError):
    def __init__(self, message: str = "Unauthorized", **kwargs: Any) -> None:
        super().__init__(code="UNAUTHORIZED", message=message, status_code=401, **kwargs)


class ForbiddenError(AppError):
    def __init__(self, message: str = "Forbidden", **kwargs: Any) -> None:
        super().__init__(code="FORBIDDEN", message=message, status_code=403, **kwargs)
