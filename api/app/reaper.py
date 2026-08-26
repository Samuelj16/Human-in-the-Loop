"""Rescue tasks whose worker died and purge expired task history.

A research run can take minutes. If the process handling it is redeployed,
OOM-killed, or (in in-process mode) simply restarted, the row stays in
`researching` forever and the UI spins with nothing behind it. The worker
heartbeats while it is alive; anything running with a stale heartbeat has been
orphaned and is failed with an honest message.

Components:
  - Orphan Reaper (`reap_stale_tasks`): Identifies active tasks in running states
    (`planning`, `researching`, `queued`) whose `heartbeat_at` or `updated_at` exceeds
    the 15-minute threshold and transitions them to `failed`.
  - In-Process Background Sweeper (`reaper_loop`): Continuous asyncio loop run in
    standalone API mode when no external Arq cron worker is available.
  - Data Retention Purger (`purge_expired_tasks`): Hard deletes tasks older than
    `settings.data_retention_days`, triggering database cascading deletes on events,
    sources, and LLM turns.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import or_, select

from app.db import SessionLocal
from app.models import ResearchTask, TaskEvent, TaskStatus, utcnow

log = logging.getLogger(__name__)

# Task states considered active and monitored by the heartbeat reaper
RUNNING_STATES = (TaskStatus.PLANNING, TaskStatus.RESEARCHING, TaskStatus.QUEUED)
# Maximum duration without a heartbeat before a task is considered orphaned
STALE_AFTER = timedelta(minutes=15)
# In-process periodic sweep interval
SWEEP_INTERVAL_SECONDS = 300

# User-facing failure explanation attached to reaped tasks
ORPHANED_MESSAGE = (
    "This run was interrupted - the worker handling it stopped responding "
    "(most likely a restart or deploy). Nothing further was charged. "
    "Start a new run to try again."
)


async def reap_stale_tasks(stale_after: timedelta = STALE_AFTER) -> int:
    """Fail orphaned tasks. Returns how many were reaped.
    
    Args:
        stale_after: Inactivity threshold duration before declaring task dead.
        
    Returns:
        int: Number of orphaned tasks marked FAILED.
    """
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
    """Background sweep loop, used when there is no arq worker to run it on a cron.
    
    Args:
        interval_seconds: Sleep duration between consecutive sweeps.
    """
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
    """arq cron worker entrypoint for reaping stale tasks.
    
    Args:
        ctx: Optional worker context.
        
    Returns:
        int: Count of reaped tasks.
    """
    return await reap_stale_tasks()


# --------------------------------------------------------------------------
# Retention
# --------------------------------------------------------------------------
async def purge_expired_tasks(retention_days: int | None = None) -> int:
    """Delete tasks past the retention window. Returns how many were removed.

    Events, sources, and turns go with them via ON DELETE CASCADE. A retention
    of 0 means "keep forever", which is a legitimate choice - but it should be a
    stated one, not an accident.
    
    Args:
        retention_days: Number of days to retain tasks. If None, uses settings.data_retention_days.
        
    Returns:
        int: Number of deleted task records.
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
    """arq cron worker entrypoint for purging expired tasks.
    
    Args:
        ctx: Optional worker context.
        
    Returns:
        int: Count of purged tasks.
    """
    return await purge_expired_tasks()

