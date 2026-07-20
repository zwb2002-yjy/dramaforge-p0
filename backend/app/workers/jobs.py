"""Thin Arq job registry. Domain jobs register here in later stages."""

from __future__ import annotations

from typing import Any


async def health_ping(ctx: dict[str, Any]) -> dict[str, str]:
    """No-op job used to prove worker process can execute tasks."""
    _ = ctx
    return {"status": "ok", "job": "health_ping"}


JOB_FUNCTIONS = [health_ping]
