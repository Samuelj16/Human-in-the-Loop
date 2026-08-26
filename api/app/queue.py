"""Job dispatch.

With REDIS_URL set, work goes to an arq worker (`arq app.worker.WorkerSettings`)
so a long research run survives an API redeploy. Without it, the same coroutine
runs in-process - handy on a laptop, and the reason `docker compose` is optional
for a first run.
"""
from __future__ import annotations

import asyncio
import logging

from app.config import settings
from app.jobs import plan_task, run_task

log = logging.getLogger(__name__)

JOBS = {"plan_task": plan_task, "run_task": run_task}

# Keeps in-process tasks from being garbage collected mid-flight.
_background: set[asyncio.Task] = set()


async def enqueue(job_name: str, task_id: str) -> None:
    if job_name not in JOBS:
        raise ValueError(f"Unknown job {job_name!r}")

    if settings.redis_url:
        from arq import create_pool
        from arq.connections import RedisSettings

        pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        try:
            await pool.enqueue_job(job_name, task_id)
            return
        finally:
            await pool.aclose()

    task = asyncio.create_task(JOBS[job_name](None, task_id))
    _background.add(task)

    def _finished(done: asyncio.Task) -> None:
        _background.discard(done)
        # Without this an exception inside a fire-and-forget task is never
        # printed anywhere, and the row just stops changing.
        if not done.cancelled() and done.exception() is not None:
            log.error(
                "background job %s for task %s crashed",
                job_name, task_id, exc_info=done.exception(),
            )

    task.add_done_callback(_finished)
