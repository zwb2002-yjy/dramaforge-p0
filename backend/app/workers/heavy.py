"""Heavy (media/inference) Arq worker settings."""

from __future__ import annotations

from arq.connections import RedisSettings

from app.config import get_settings
from app.workers.jobs import JOB_FUNCTIONS


def _redis_settings() -> RedisSettings:
    settings = get_settings()
    return RedisSettings.from_dsn(settings.redis_url)


class WorkerSettings:
    """Arq WorkerSettings for the heavy queue."""

    functions = JOB_FUNCTIONS
    redis_settings = _redis_settings()
    queue_name = get_settings().arq_heavy_queue_name
    max_jobs = 2
    job_timeout = 1800
    keep_result = 60
