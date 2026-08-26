"""arq worker configuration and entrypoint: `arq app.worker.WorkerSettings`.

This module configures the distributed background worker powered by Arq and Redis:
  - Startup Hook (`startup`): Initializes database schema and mappings prior to accepting jobs.
  - Registered Job Functions:
      * `plan_task`: Phase 1 LLM planner and cost estimator.
      * `run_task`: Phase 2 tool loop execution and citation audit.
      * `reap_job`: Periodic sweep for orphaned tasks whose worker process crashed or restarted.
      * `retention_job`: Nightly purge of tasks older than DATA_RETENTION_DAYS.
  - Worker Lifespan & Timeouts: Extends default job timeout to 20 minutes to accommodate deep multi-turn research runs.
"""
from __future__ import annotations

from arq import cron
from arq.connections import RedisSettings

from app.config import settings
from app.jobs import plan_task, run_task
from app.reaper import reap_job, retention_job


async def startup(ctx: dict) -> None:
    """Ensure the schema exists before the worker takes its first job.
    
    Args:
        ctx: Worker context dictionary provided by Arq runtime.
    """
    from app.db import init_db

    await init_db()


class WorkerSettings:
    """arq entrypoint: `arq app.worker.WorkerSettings`.

    Runs the same jobs the API can run in-process, plus the periodic reaper and
    retention sweeps.
    """
    # List of async job functions callable by name
    functions = [plan_task, run_task, reap_job, retention_job]
    # Periodic background cron schedules
    cron_jobs = [
        # Sweep for tasks orphaned by a crashed or redeployed worker every 5 minutes
        cron(reap_job, minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}),
        # Retention sweep, nightly at 03:17 UTC. No-op unless DATA_RETENTION_DAYS is set > 0.
        cron(retention_job, hour={3}, minute={17}),
    ]
    # Initialization hook
    on_startup = startup
    # Redis connection parameters
    redis_settings = RedisSettings.from_dsn(settings.redis_url or "redis://localhost:6379")
    # Maximum execution duration per job (20 minutes) so long research runs are not killed early
    job_timeout = 60 * 20
    # Maximum concurrent jobs per worker process
    max_jobs = 10

