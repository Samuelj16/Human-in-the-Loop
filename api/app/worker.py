"""arq worker entrypoint: `arq app.worker.WorkerSettings`."""
from __future__ import annotations

from arq import cron
from arq.connections import RedisSettings

from app.config import settings
from app.jobs import plan_task, run_task
from app.reaper import reap_job, retention_job


async def startup(ctx: dict) -> None:
    """Ensure the schema exists before the worker takes its first job."""
    from app.db import init_db

    await init_db()


class WorkerSettings:
    """arq entrypoint: `arq app.worker.WorkerSettings`.

    Runs the same jobs the API can run in-process, plus the periodic reaper and
    retention sweeps.
    """
    functions = [plan_task, run_task, reap_job, retention_job]
    # Sweep for tasks orphaned by a crashed or redeployed worker.
    cron_jobs = [
        cron(reap_job, minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}),
        # Retention sweep, nightly. No-op unless DATA_RETENTION_DAYS is set.
        cron(retention_job, hour={3}, minute={17}),
    ]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(settings.redis_url or "redis://localhost:6379")
    # A research run is long; do not let arq reclaim it early.
    job_timeout = 60 * 20
    max_jobs = 10
