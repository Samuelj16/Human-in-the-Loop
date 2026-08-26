"""Rescue tasks whose worker died.

A research run can take minutes. If the process handling it is redeployed,
OOM-killed, or (in in-process mode) simply restarted, the row stays in
`researching` forever and the UI spins with nothing behind it. The worker
heartbeats while it is alive; anything running with a stale heartbeat has been
orphaned and is failed with an honest message.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import or_, select

from app.db import SessionLocal
from app.models import ResearchTask, TaskEvent, TaskStatus, utcnow

log = logging.getLogger(__name__)

RUNNING_STATES = (TaskStatus.PLANNING, TaskStatus.RESEARCHING, TaskStatus.QUEUED)
STALE_AFTER = timedelta(minutes=15)
SWEEP_INTERVAL_SECONDS = 300

ORPHANED_MESSAGE = (
    "This run was interrupted - the worker handling it stopped responding "
    "(most likely a restart or deploy). Nothing further was charged. "
    "Start a new run to try again."
)


async def reap_stale_tasks(stale_after: timedelta = STALE_AFTER) -> int:
    """Fail orphaned tasks. Returns how many were reaped."""
    cutoff = utcnow() - stale_after

    async with SessionLocal() as session:
        stale = list(
            (
                await session.scalars(
                    select(ResearchTask).where(
                        ResearchTask.status.in_(RUNNING_STATES),
                        or_(
                            ResearchTask.heartbeat_at < cutoff,
                            # Never heartbeated at all - fall back to when the
                            # row was last written.
                            ResearchTask.heartbeat_at.is_(None),
                        ),
                        ResearchTask.updated_at < cutoff,
                    )
                )
            ).all()
        )

        for task in stale:
            log.warning("reaping orphaned task %s (status=%s)", task.id, task.status)
            task.status = TaskStatus.FAILED
            task.error = ORPHANED_MESSAGE
            session.add(
                TaskEvent(task_id=task.id, kind="error", message=ORPHANED_MESSAGE)
            )

        if stale:
            await session.commit()

    return len(stale)


async def reaper_loop(interval_seconds: int = SWEEP_INTERVAL_SECONDS) -> None:
    """Background sweep, used when there is no arq worker to run it on a cron."""
    while True:
        try:
            reaped = await reap_stale_tasks()
            if reaped:
                log.info("reaper failed %d orphaned task(s)", reaped)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - a sweep failure must not kill the loop
            log.exception("reaper sweep failed")
        await asyncio.sleep(interval_seconds)


async def reap_job(ctx: dict | None = None) -> int:
    """arq entrypoint."""
    return await reap_stale_tasks()


# --------------------------------------------------------------------------
# Retention
# --------------------------------------------------------------------------
async def purge_expired_tasks(retention_days: int | None = None) -> int:
    """Delete tasks past the retention window. Returns how many were removed.

    Events, sources, and turns go with them via ON DELETE CASCADE. A retention
    of 0 means "keep forever", which is a legitimate choice - but it should be a
    stated one, not an accident.
    """
    from app.config import settings

    days = settings.data_retention_days if retention_days is None else retention_days
    if days <= 0:
        return 0

    cutoff = utcnow() - timedelta(days=days)

    async with SessionLocal() as session:
        doomed = list(
            (
                await session.scalars(
                    select(ResearchTask).where(ResearchTask.created_at < cutoff)
                )
            ).all()
        )
        for task in doomed:
            await session.delete(task)
        if doomed:
            await session.commit()
            log.info("purged %d task(s) older than %d days", len(doomed), days)

    return len(doomed)


async def retention_job(ctx: dict | None = None) -> int:
    """arq entrypoint."""
    return await purge_expired_tasks()
