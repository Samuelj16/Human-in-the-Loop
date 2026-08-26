"""Orphaned tasks must not spin forever in the UI."""
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ResearchTask, TaskEvent, TaskStatus, utcnow
from app.reaper import ORPHANED_MESSAGE, reap_stale_tasks


async def _make_task(session: AsyncSession, user, *, status, age_minutes, heartbeat):
    old = utcnow() - timedelta(minutes=age_minutes)
    task = ResearchTask(
        user_id=user.id,
        query="A question that needs researching",
        status=status,
        created_at=old,
        updated_at=old,
        heartbeat_at=(utcnow() - timedelta(minutes=heartbeat)) if heartbeat else None,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


async def test_reaps_a_task_whose_worker_stopped_heartbeating(
    db_session: AsyncSession, test_user
):
    task = await _make_task(
        db_session, test_user, status=TaskStatus.RESEARCHING, age_minutes=60, heartbeat=45
    )

    reaped = await reap_stale_tasks()

    assert reaped == 1
    await db_session.refresh(task)
    assert task.status == TaskStatus.FAILED
    assert task.error == ORPHANED_MESSAGE

    # The user gets told what happened, in the timeline they are already watching.
    events = list(
        (await db_session.scalars(select(TaskEvent).where(TaskEvent.task_id == task.id))).all()
    )
    assert [e.kind for e in events] == ["error"]


async def test_a_task_that_never_heartbeated_is_still_reaped(
    db_session: AsyncSession, test_user
):
    task = await _make_task(
        db_session, test_user, status=TaskStatus.QUEUED, age_minutes=60, heartbeat=None
    )

    assert await reap_stale_tasks() == 1
    await db_session.refresh(task)
    assert task.status == TaskStatus.FAILED


async def test_a_live_run_is_left_alone(db_session: AsyncSession, test_user):
    """Long runs are normal; only a stale heartbeat means orphaned."""
    task = await _make_task(
        db_session, test_user, status=TaskStatus.RESEARCHING, age_minutes=60, heartbeat=1
    )

    assert await reap_stale_tasks() == 0
    await db_session.refresh(task)
    assert task.status == TaskStatus.RESEARCHING


async def test_a_recent_task_is_left_alone(db_session: AsyncSession, test_user):
    task = await _make_task(
        db_session, test_user, status=TaskStatus.RESEARCHING, age_minutes=1, heartbeat=None
    )

    assert await reap_stale_tasks() == 0
    await db_session.refresh(task)
    assert task.status == TaskStatus.RESEARCHING


@pytest.mark.parametrize(
    "status", [TaskStatus.COMPLETE, TaskStatus.FAILED, TaskStatus.CANCELLED]
)
async def test_finished_tasks_are_never_touched(
    db_session: AsyncSession, test_user, status
):
    task = await _make_task(
        db_session, test_user, status=status, age_minutes=600, heartbeat=None
    )

    assert await reap_stale_tasks() == 0
    await db_session.refresh(task)
    assert task.status == status


# -- retention --------------------------------------------------------------
async def test_retention_purges_old_tasks_and_their_children(
    db_session: AsyncSession, test_user
):
    old = await _make_task(
        db_session, test_user, status=TaskStatus.COMPLETE, age_minutes=60 * 24 * 40,
        heartbeat=None,
    )
    db_session.add(TaskEvent(task_id=old.id, kind="status", message="something", seq=1))
    await db_session.commit()
    old_id = old.id

    from app.reaper import purge_expired_tasks

    assert await purge_expired_tasks(retention_days=30) == 1

    # The purge ran in its own session, so drop this one's identity map before
    # asserting - otherwise `get` answers from cache and never touches the DB.
    db_session.expunge_all()
    assert await db_session.get(ResearchTask, old_id) is None

    # Children go with the parent rather than being orphaned.
    leftovers = list(
        (await db_session.scalars(select(TaskEvent).where(TaskEvent.task_id == old_id))).all()
    )
    assert leftovers == []


async def test_retention_keeps_recent_tasks(db_session: AsyncSession, test_user):
    recent = await _make_task(
        db_session, test_user, status=TaskStatus.COMPLETE, age_minutes=60, heartbeat=None
    )

    from app.reaper import purge_expired_tasks

    assert await purge_expired_tasks(retention_days=30) == 0
    assert await db_session.get(ResearchTask, recent.id) is not None


async def test_retention_disabled_by_default_keeps_everything(
    db_session: AsyncSession, test_user
):
    """0 means keep forever - an explicit choice, not an accidental deletion."""
    ancient = await _make_task(
        db_session, test_user, status=TaskStatus.COMPLETE,
        age_minutes=60 * 24 * 3650, heartbeat=None,
    )

    from app.reaper import purge_expired_tasks

    assert await purge_expired_tasks(retention_days=0) == 0
    assert await db_session.get(ResearchTask, ancient.id) is not None
