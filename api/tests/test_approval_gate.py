"""The approval gate authorises spending money, so its edges are tested."""
import asyncio

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ResearchTask, TaskEvent, TaskStatus


async def _awaiting_task(
    client: AsyncClient, headers: dict, session: AsyncSession
) -> ResearchTask:
    res = await client.post(
        "/api/tasks", json={"query": "What happened to the widget market?"}, headers=headers
    )
    assert res.status_code == 201
    task = await session.get(ResearchTask, res.json()["id"])
    task.status = TaskStatus.AWAITING_APPROVAL
    task.plan = ["Original step one", "Original step two"]
    task.model = "claude-opus-5"
    task.estimated_cost_usd = 0.21
    await session.commit()
    await session.refresh(task)
    return task


async def test_concurrent_approvals_only_start_one_run(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession, monkeypatch
):
    """Two clicks must not buy two research runs."""
    task = await _awaiting_task(client, auth_headers, db_session)

    enqueued: list[str] = []

    async def recording_enqueue(job_name: str, task_id: str):
        enqueued.append(task_id)

    monkeypatch.setattr("app.routers.tasks.enqueue", recording_enqueue)

    body = {"plan": ["Original step one", "Original step two"], "answers": {}}
    first, second = await asyncio.gather(
        client.post(f"/api/tasks/{task.id}/approve", json=body, headers=auth_headers),
        client.post(f"/api/tasks/{task.id}/approve", json=body, headers=auth_headers),
        return_exceptions=True,
    )

    codes = sorted(
        r.status_code for r in (first, second) if not isinstance(r, Exception)
    )
    assert 200 in codes, f"one approval must succeed, got {codes}"
    # The loser is rejected - never a silent second run.
    assert codes.count(200) == 1, f"exactly one approval may win, got {codes}"
    assert len(enqueued) == 1, "exactly one research run may be enqueued"


async def test_second_approval_after_the_first_is_rejected(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession
):
    task = await _awaiting_task(client, auth_headers, db_session)
    body = {"plan": ["Original step one"], "answers": {}}

    first = await client.post(
        f"/api/tasks/{task.id}/approve", json=body, headers=auth_headers
    )
    second = await client.post(
        f"/api/tasks/{task.id}/approve", json=body, headers=auth_headers
    )

    assert first.status_code == 200
    assert second.status_code in (400, 409)


async def test_edited_plan_is_recorded_as_edited(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession
):
    """Knowing the human changed the plan is the point of the gate."""
    task = await _awaiting_task(client, auth_headers, db_session)

    res = await client.post(
        f"/api/tasks/{task.id}/approve",
        json={
            "plan": ["A completely different step"],
            "answers": {"Which year?": "2026"},
        },
        headers=auth_headers,
    )

    assert res.status_code == 200
    payload = res.json()
    assert payload["plan_edited_by_user"] is True
    assert payload["plan"] == ["A completely different step"]
    assert payload["clarification_answers"] == {"Which year?": "2026"}


async def test_unedited_plan_is_not_recorded_as_edited(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession
):
    task = await _awaiting_task(client, auth_headers, db_session)

    res = await client.post(
        f"/api/tasks/{task.id}/approve",
        json={"plan": ["Original step one", "Original step two"], "answers": {}},
        headers=auth_headers,
    )

    assert res.status_code == 200
    assert res.json()["plan_edited_by_user"] is False


async def test_estimate_reflects_the_current_plan(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession
):
    """The price shown must respond to the user's edits, not the original draft."""
    task = await _awaiting_task(client, auth_headers, db_session)

    small = await client.get(f"/api/tasks/{task.id}/estimate", headers=auth_headers)
    assert small.status_code == 200
    assert small.json()["priced"] is True

    task.plan = ["one", "two", "three", "four", "five", "six"]
    await db_session.commit()

    big = await client.get(f"/api/tasks/{task.id}/estimate", headers=auth_headers)
    assert big.json()["expected_usd"] > small.json()["expected_usd"]


async def test_estimate_is_not_readable_by_another_user(
    client: AsyncClient, auth_headers: dict, another_auth_headers: dict,
    db_session: AsyncSession,
):
    task = await _awaiting_task(client, auth_headers, db_session)

    res = await client.get(
        f"/api/tasks/{task.id}/estimate", headers=another_auth_headers
    )

    assert res.status_code == 404


# -- incremental event feed -------------------------------------------------
async def test_events_endpoint_returns_only_what_is_new(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession
):
    task = await _awaiting_task(client, auth_headers, db_session)
    for seq in (1, 2, 3):
        db_session.add(
            TaskEvent(task_id=task.id, kind="status", message=f"event {seq}", seq=seq)
        )
    await db_session.commit()

    everything = await client.get(
        f"/api/tasks/{task.id}/events", headers=auth_headers
    )
    assert [e["seq"] for e in everything.json()["events"]] == [1, 2, 3]
    assert everything.json()["cursor"] == 3

    incremental = await client.get(
        f"/api/tasks/{task.id}/events?after=2", headers=auth_headers
    )
    payload = incremental.json()
    assert [e["seq"] for e in payload["events"]] == [3]
    assert payload["cursor"] == 3
    assert payload["done"] is False


async def test_events_cursor_holds_when_nothing_is_new(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession
):
    task = await _awaiting_task(client, auth_headers, db_session)
    db_session.add(TaskEvent(task_id=task.id, kind="status", message="only", seq=1))
    await db_session.commit()

    res = await client.get(f"/api/tasks/{task.id}/events?after=1", headers=auth_headers)

    assert res.json()["events"] == []
    assert res.json()["cursor"] == 1, "an empty page must not rewind the cursor"


async def test_events_report_terminal_state_so_polling_can_stop(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession
):
    task = await _awaiting_task(client, auth_headers, db_session)
    task.status = TaskStatus.COMPLETE
    await db_session.commit()

    res = await client.get(f"/api/tasks/{task.id}/events", headers=auth_headers)

    assert res.json()["done"] is True


async def test_events_are_not_readable_by_another_user(
    client: AsyncClient, auth_headers: dict, another_auth_headers: dict,
    db_session: AsyncSession,
):
    task = await _awaiting_task(client, auth_headers, db_session)

    res = await client.get(f"/api/tasks/{task.id}/events", headers=another_auth_headers)

    assert res.status_code == 404
