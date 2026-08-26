"""Tests for research task management endpoints."""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ResearchTask, Source, TaskEvent, TaskStatus


@pytest.mark.asyncio
async def test_create_task(client: AsyncClient, auth_headers: dict[str, str]):
    res = await client.post(
        "/api/tasks",
        json={"query": "Research recent breakthroughs in battery chemistry"},
        headers=auth_headers,
    )
    assert res.status_code == 201
    data = res.json()
    assert data["query"] == "Research recent breakthroughs in battery chemistry"
    assert data["status"] in (TaskStatus.QUEUED, TaskStatus.PLANNING, TaskStatus.AWAITING_APPROVAL)
    assert "id" in data


@pytest.mark.asyncio
async def test_list_tasks(client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession, test_user):
    task1 = ResearchTask(user_id=test_user.id, query="Query 1", status=TaskStatus.COMPLETE)
    task2 = ResearchTask(user_id=test_user.id, query="Query 2", status=TaskStatus.QUEUED)
    db_session.add_all([task1, task2])
    await db_session.commit()

    res = await client.get("/api/tasks", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert len(data) >= 2
    queries = [t["query"] for t in data]
    assert "Query 1" in queries
    assert "Query 2" in queries


@pytest.mark.asyncio
async def test_get_task_detail(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_user,
):
    task = ResearchTask(
        user_id=test_user.id,
        query="Explain solid-state battery tech",
        status=TaskStatus.AWAITING_APPROVAL,
        plan=["Step 1: Check cathodes", "Step 2: Check electrolytes"],
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)

    event = TaskEvent(
        task_id=task.id,
        kind="status",
        message="Drafting complete",
    )
    source = Source(
        task_id=task.id,
        url="https://nature.com/articles/sample",
        title="Solid state advances",
        snippet="Recent advances in solid state electrolytes...",
    )
    db_session.add_all([event, source])
    await db_session.commit()

    res = await client.get(f"/api/tasks/{task.id}", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == task.id
    assert len(data["events"]) == 1
    assert data["events"][0]["message"] == "Drafting complete"
    assert len(data["sources"]) == 1
    assert data["sources"][0]["url"] == "https://nature.com/articles/sample"


@pytest.mark.asyncio
async def test_approve_plan(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_user,
):
    task = ResearchTask(
        user_id=test_user.id,
        query="Explain quantum computing algorithms",
        status=TaskStatus.AWAITING_APPROVAL,
        plan=["Step 1: Draft initial overview"],
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)

    res = await client.post(
        f"/api/tasks/{task.id}/approve",
        json={
            "plan": ["Step 1: Survey Grover's algorithm", "Step 2: Survey Shor's algorithm"],
            "answers": {"focus": "NISQ era applications"},
        },
        headers=auth_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == TaskStatus.RESEARCHING
    assert data["plan_edited_by_user"] is True
    assert len(data["plan"]) == 2


@pytest.mark.asyncio
async def test_approve_plan_invalid_status(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_user,
):
    task = ResearchTask(
        user_id=test_user.id,
        query="Sample query",
        status=TaskStatus.COMPLETE,
        plan=["Step 1"],
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)

    res = await client.post(
        f"/api/tasks/{task.id}/approve",
        json={"plan": ["New Step"], "answers": {}},
        headers=auth_headers,
    )
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_approve_plan_rejects_oversized_prompt_fields(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_user,
):
    task = ResearchTask(
        user_id=test_user.id,
        query="Bound approval prompt inputs",
        status=TaskStatus.AWAITING_APPROVAL,
        plan=["Step 1"],
    )
    db_session.add(task)
    await db_session.commit()

    res = await client.post(
        f"/api/tasks/{task.id}/approve",
        json={"plan": ["x" * 501], "answers": {}},
        headers=auth_headers,
    )

    assert res.status_code == 422


@pytest.mark.asyncio
async def test_cancel_task(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_user,
):
    task = ResearchTask(
        user_id=test_user.id,
        query="Cancel me",
        status=TaskStatus.RESEARCHING,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)

    res = await client.post(f"/api/tasks/{task.id}/cancel", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["status"] == TaskStatus.CANCELLED


@pytest.mark.asyncio
async def test_toggle_source_exclusion(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_user,
):
    task = ResearchTask(
        user_id=test_user.id,
        query="Source exclusion test",
        status=TaskStatus.RESEARCHING,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)

    source = Source(
        task_id=task.id,
        url="https://spammy-site.com",
        title="Spam",
        snippet="Low quality content",
        excluded=False,
    )
    db_session.add(source)
    await db_session.commit()
    await db_session.refresh(source)

    # Exclude source
    res = await client.post(
        f"/api/tasks/{task.id}/sources/{source.id}/toggle",
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["excluded"] is True

    # Toggle back to included
    res2 = await client.post(
        f"/api/tasks/{task.id}/sources/{source.id}/toggle",
        headers=auth_headers,
    )
    assert res2.status_code == 200
    assert res2.json()["excluded"] is False


@pytest.mark.asyncio
async def test_share_task(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_user,
):
    task = ResearchTask(
        user_id=test_user.id,
        query="Shareable research",
        status=TaskStatus.COMPLETE,
        report_markdown="# Comprehensive Report",
        is_public=False,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)

    res = await client.post(f"/api/tasks/{task.id}/share", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["is_public"] is True
    assert data["share_id"] is not None


@pytest.mark.asyncio
async def test_task_access_isolation(
    client: AsyncClient,
    another_auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_user,
):
    # Task owned by test_user
    task = ResearchTask(
        user_id=test_user.id,
        query="Private query",
        status=TaskStatus.COMPLETE,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)

    # another_user tries to get task
    res = await client.get(f"/api/tasks/{task.id}", headers=another_auth_headers)
    assert res.status_code == 404
