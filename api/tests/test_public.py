"""Tests for public report sharing endpoints."""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ResearchTask, Source, TaskStatus


@pytest.mark.asyncio
async def test_get_public_report_success(client: AsyncClient, db_session: AsyncSession, test_user):
    task = ResearchTask(
        user_id=test_user.id,
        query="Public query on fusion energy",
        status=TaskStatus.COMPLETE,
        report_markdown="# Fusion Progress\nNet energy gain sustained for 10 minutes [1].",
        share_id="fusion-share-12345",
        is_public=True,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)

    source1 = Source(
        task_id=task.id,
        url="https://fusion-lab.org/press",
        title="Fusion Press Release",
        snippet="Sustained Q>1 for 10 minutes.",
        excluded=False,
    )
    source2 = Source(
        task_id=task.id,
        url="https://spam.com",
        title="Spam",
        snippet="Excluded source",
        excluded=True,
    )
    db_session.add_all([source1, source2])
    await db_session.commit()

    res = await client.get(f"/api/public/reports/{task.share_id}")
    assert res.status_code == 200
    data = res.json()
    assert data["query"] == "Public query on fusion energy"
    assert "Fusion Progress" in data["report_markdown"]
    assert len(data["sources"]) == 1
    assert data["sources"][0]["url"] == "https://fusion-lab.org/press"


@pytest.mark.asyncio
async def test_get_public_report_not_public(client: AsyncClient, db_session: AsyncSession, test_user):
    task = ResearchTask(
        user_id=test_user.id,
        query="Private query",
        status=TaskStatus.COMPLETE,
        report_markdown="# Secret Report",
        share_id="private-share-999",
        is_public=False,
    )
    db_session.add(task)
    await db_session.commit()

    res = await client.get(f"/api/public/reports/{task.share_id}")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_get_public_report_nonexistent(client: AsyncClient):
    res = await client.get("/api/public/reports/does-not-exist")
    assert res.status_code == 404

