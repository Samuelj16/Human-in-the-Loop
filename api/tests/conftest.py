"""Pytest fixtures for API and agent tests."""
from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import AsyncIterator
from pathlib import Path

# Ensure api directory is on sys.path
api_root = Path(__file__).resolve().parent.parent
if str(api_root) not in sys.path:
    sys.path.insert(0, str(api_root))

TEST_DB_PATH = api_root / "test_hitl.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DB_PATH}"
os.environ["JWT_SECRET"] = "nCYOgo2Meev8EPV_ObckSqb5IQCYSWRuijKl9pQIXjS8Jdq5fml8dQwswXEPrGVk"
os.environ["ENVIRONMENT"] = "development"
os.environ["TAVILY_API_KEY"] = ""
# The whole suite shares one client IP; the limiter is unit-tested directly
# in tests/test_ratelimit.py instead.
os.environ["RATE_LIMIT_ENABLED"] = "false"

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.models  # register all models with Base
from app.config import settings
from app.db import Base, get_session
from app.llm.base import (
    LLMProvider,
    LLMResponse,
    Message,
    ToolCall,
    ToolSpec,
    Usage,
)
from app.main import app
from app.models import ResearchTask, Source, TaskEvent, User
from app.search.base import SearchClient, SearchResult
from app.security import hash_password

test_engine = create_async_engine(
    f"sqlite+aiosqlite:///{TEST_DB_PATH}",
    poolclass=NullPool,
    connect_args={"check_same_thread": False},
    future=True,
)
TestSessionLocal = async_sessionmaker(
    test_engine, class_=AsyncSession, expire_on_commit=False
)


@pytest_asyncio.fixture(autouse=True)
async def setup_db(monkeypatch):
    import app.db
    import app.jobs
    import app.reaper

    app.db.engine = test_engine
    app.db.SessionLocal = TestSessionLocal
    # These modules bind SessionLocal at import time, so each needs redirecting.
    app.jobs.SessionLocal = TestSessionLocal
    app.reaper.SessionLocal = TestSessionLocal

    # Mock enqueue in API routes by default to avoid unmocked background LLM calls
    async def _noop_enqueue(job_name: str, task_id: str):
        pass

    monkeypatch.setattr("app.routers.tasks.enqueue", _noop_enqueue)

    async with test_engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: Base.metadata.drop_all(sync_conn, checkfirst=True))
        await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn, checkfirst=True))
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: Base.metadata.drop_all(sync_conn, checkfirst=True))


async def override_get_session() -> AsyncIterator[AsyncSession]:
    async with TestSessionLocal() as session:
        yield session


app.dependency_overrides[get_session] = override_get_session


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    async with TestSessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class MockLLMProvider(LLMProvider):
    name = "mock"
    model = "mock-model"

    def __init__(self, responses: list[LLMResponse] | None = None) -> None:
        self.responses = list(responses or [])
        self.call_count = 0
        self.last_prompt = ""

    async def complete(
        self,
        *,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        max_tokens: int = 8000,
        cache_prefix: bool = False,
    ) -> LLMResponse:
        self.call_count += 1
        self.last_cache_prefix = cache_prefix
        if self.responses:
            return self.responses.pop(0)
        return LLMResponse(
            text='{"plan": ["Step 1: Collect info", "Step 2: Synthesize findings"], "clarifying_questions": ["What is the target geography?"], "restated_question": "Comprehensive research."}',
            tool_calls=[],
            stop_reason="end_turn",
            usage=Usage(input_tokens=100, output_tokens=50),
        )


    async def complete_json(
        self,
        *,
        system: str,
        messages: list[Message],
        schema: dict,
        max_tokens: int = 2000,
    ) -> tuple[dict, LLMResponse]:
        """Constrained output, mocked: the scripted text must parse as JSON."""
        response = await self.complete(
            system=system, messages=messages, max_tokens=max_tokens
        )
        self.last_schema = schema
        text = response.text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
        return json.loads(text), response


class MockSearchClient(SearchClient):
    name = "mock_search"

    def __init__(self, results: list[SearchResult] | None = None) -> None:
        self.results = results or [
            SearchResult(
                url="https://example.com/item1",
                title="Example Item 1",
                snippet="Sample snippet for testing search results.",
            )
        ]
        self.searches: list[str] = []

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        self.searches.append(query)
        return self.results


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession) -> User:
    user = User(
        email="test@example.com",
        hashed_password=hash_password("password1234"),
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def auth_headers(client: AsyncClient, test_user: User) -> dict[str, str]:
    res = await client.post(
        "/api/auth/login",
        json={"email": "test@example.com", "password": "password1234"},
    )
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def another_auth_headers(client: AsyncClient, db_session: AsyncSession) -> dict[str, str]:
    user2 = User(
        email="other@example.com",
        hashed_password=hash_password("password5678"),
    )
    db_session.add(user2)
    await db_session.commit()
    res = await client.post(
        "/api/auth/login",
        json={"email": "other@example.com", "password": "password5678"},
    )
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
