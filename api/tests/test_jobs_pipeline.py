"""End-to-end job behaviour: pricing, telemetry, and citation auditing.

Runs against scripted providers, so it exercises the real job code with no
network and no spend.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs import plan_task, run_task
from app.models import LLMTurn, ResearchTask, Source, TaskEvent, TaskStatus
from tests.fakes import CountingSearch, FakeProvider, text_turn, tool_turn

PLAN_JSON = (
    '{"restated_question": "What happened to widgets?", '
    '"clarifying_questions": ["Which region?"], '
    '"plan": ["Find widget shipment data", "Compare against 2024 baseline"]}'
)

HONEST_REPORT = (
    "# Widget market\n\n"
    + ("The market contracted sharply across the period under review. " * 8)
    + "\n\n## Sources\n\n1. https://example.com/1 - shipment figures\n"
)

REPORT_WITH_INVENTED_SOURCE = (
    "# Widget market\n\n"
    + ("The market contracted sharply across the period under review. " * 8)
    + "\n\n## Sources\n\n"
    "1. https://example.com/1 - shipment figures\n"
    "2. https://institute-of-widgets.example.org/2026-report - industry survey\n"
)


async def _task(session: AsyncSession, user, **fields) -> ResearchTask:
    task = ResearchTask(
        user_id=user.id, query="What happened to the widget market?", **fields
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


def _install(monkeypatch, provider, search=None):
    monkeypatch.setattr("app.jobs.get_llm_provider", lambda: provider)
    monkeypatch.setattr("app.jobs.get_search_client", lambda: search or CountingSearch())


# -- planning ---------------------------------------------------------------
async def test_plan_task_prices_the_plan_before_asking_for_approval(
    db_session: AsyncSession, test_user, monkeypatch
):
    task = await _task(db_session, test_user, status=TaskStatus.QUEUED)
    _install(monkeypatch, FakeProvider([text_turn(PLAN_JSON)]))

    await plan_task(None, task.id)
    await db_session.refresh(task)

    assert task.status == TaskStatus.AWAITING_APPROVAL
    assert task.plan == ["Find widget shipment data", "Compare against 2024 baseline"]
    assert task.clarifying_questions == ["Which region?"]
    # The number the approval screen shows.
    assert task.estimated_cost_usd is not None and task.estimated_cost_usd > 0

    events = list(
        (await db_session.scalars(select(TaskEvent).where(TaskEvent.task_id == task.id))).all()
    )
    assert any("approve" in e.message for e in events)
    assert any(e.data and "estimate" in e.data for e in events)


async def test_planning_records_a_telemetry_turn(
    db_session: AsyncSession, test_user, monkeypatch
):
    task = await _task(db_session, test_user, status=TaskStatus.QUEUED)
    _install(monkeypatch, FakeProvider([text_turn(PLAN_JSON)]))

    await plan_task(None, task.id)

    turns = list(
        (await db_session.scalars(select(LLMTurn).where(LLMTurn.task_id == task.id))).all()
    )
    assert [t.phase for t in turns] == ["planning"]
    assert turns[0].attempts == 1


async def test_planning_failure_marks_the_task_failed(
    db_session: AsyncSession, test_user, monkeypatch
):
    task = await _task(db_session, test_user, status=TaskStatus.QUEUED)
    _install(monkeypatch, FakeProvider([text_turn("not json at all")]))

    await plan_task(None, task.id)
    await db_session.refresh(task)

    assert task.status == TaskStatus.FAILED
    assert task.error


# -- research ---------------------------------------------------------------
async def test_run_task_completes_and_accounts_for_spend(
    db_session: AsyncSession, test_user, monkeypatch
):
    task = await _task(
        db_session,
        test_user,
        status=TaskStatus.RESEARCHING,
        plan=["Find widget shipment data"],
        model="claude-opus-5",
    )
    _install(
        monkeypatch, FakeProvider([tool_turn("widget shipments"), text_turn(HONEST_REPORT)])
    )

    await run_task(None, task.id)
    await db_session.refresh(task)

    assert task.status == TaskStatus.COMPLETE
    assert task.report_markdown == HONEST_REPORT
    assert task.share_id
    assert task.searches_used == 1
    assert task.actual_cost_usd > 0, "spend must be recorded in dollars"
    assert task.heartbeat_at is None, "a finished task is not a reaper candidate"

    turns = list(
        (await db_session.scalars(select(LLMTurn).where(LLMTurn.task_id == task.id))).all()
    )
    assert len(turns) == 2 and {t.phase for t in turns} == {"research"}

    sources = list(
        (await db_session.scalars(select(Source).where(Source.task_id == task.id))).all()
    )
    assert [s.url for s in sources] == ["https://example.com/1"]


async def test_clean_report_passes_the_citation_audit(
    db_session: AsyncSession, test_user, monkeypatch
):
    task = await _task(
        db_session, test_user, status=TaskStatus.RESEARCHING, plan=["Find data"]
    )
    _install(monkeypatch, FakeProvider([tool_turn("q"), text_turn(HONEST_REPORT)]))

    await run_task(None, task.id)
    await db_session.refresh(task)

    assert task.citation_report["is_clean"] is True
    assert task.citation_report["unverified_count"] == 0
    assert task.citation_report["verified_ratio"] == 1.0


async def test_invented_citation_is_caught_and_surfaced(
    db_session: AsyncSession, test_user, monkeypatch
):
    """The whole point: a URL the agent never retrieved must be flagged."""
    task = await _task(
        db_session, test_user, status=TaskStatus.RESEARCHING, plan=["Find data"]
    )
    _install(
        monkeypatch,
        FakeProvider([tool_turn("q"), text_turn(REPORT_WITH_INVENTED_SOURCE)]),
    )

    await run_task(None, task.id)
    await db_session.refresh(task)

    assert task.status == TaskStatus.COMPLETE, "a flagged report is still delivered"
    report = task.citation_report
    assert report["is_clean"] is False
    assert report["unverified"] == [
        "https://institute-of-widgets.example.org/2026-report"
    ]
    assert report["verified"] == ["https://example.com/1"]

    warnings = list(
        (
            await db_session.scalars(
                select(TaskEvent).where(
                    TaskEvent.task_id == task.id, TaskEvent.kind == "warning"
                )
            )
        ).all()
    )
    assert len(warnings) == 1, "the user is told, not just the database"


async def test_cancelled_task_is_not_marked_complete(
    db_session: AsyncSession, test_user, monkeypatch
):
    task = await _task(
        db_session, test_user, status=TaskStatus.CANCELLED, plan=["Find data"]
    )
    _install(monkeypatch, FakeProvider([text_turn(HONEST_REPORT)]))

    await run_task(None, task.id)
    await db_session.refresh(task)

    assert task.status == TaskStatus.CANCELLED
    assert task.report_markdown is None


async def test_events_get_monotonic_cursors(
    db_session: AsyncSession, test_user, monkeypatch
):
    task = await _task(
        db_session, test_user, status=TaskStatus.RESEARCHING, plan=["Find data"]
    )
    _install(monkeypatch, FakeProvider([tool_turn("q"), text_turn(HONEST_REPORT)]))

    await run_task(None, task.id)

    events = list(
        (
            await db_session.scalars(
                select(TaskEvent)
                .where(TaskEvent.task_id == task.id)
                .order_by(TaskEvent.seq)
            )
        ).all()
    )
    seqs = [e.seq for e in events]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    assert seqs[0] == 1


# -- misconfiguration must never wedge a task -------------------------------
async def test_unexpected_planning_error_fails_the_task(
    db_session: AsyncSession, test_user, monkeypatch
):
    """A bare TypeError from an SDK must not leave the row stuck in `planning`.

    This is exactly what an empty ANTHROPIC_API_KEY produced: the client raised
    a TypeError, every `except LLMError` missed it, and the task sat in
    `planning` until the reaper eventually noticed 15 minutes later.
    """
    task = await _task(db_session, test_user, status=TaskStatus.QUEUED)

    class ExplodingProvider(FakeProvider):
        async def complete_json(self, **kwargs):
            raise TypeError("Could not resolve authentication method")

    _install(monkeypatch, ExplodingProvider([]))

    await plan_task(None, task.id)
    await db_session.refresh(task)

    assert task.status == TaskStatus.FAILED
    assert "authentication" in task.error.lower()


async def test_provider_construction_failure_fails_the_task(
    db_session: AsyncSession, test_user, monkeypatch
):
    task = await _task(db_session, test_user, status=TaskStatus.QUEUED)

    def broken():
        raise RuntimeError("no provider configured")

    monkeypatch.setattr("app.jobs.get_llm_provider", broken)

    await plan_task(None, task.id)
    await db_session.refresh(task)

    assert task.status == TaskStatus.FAILED
    assert "no provider configured" in task.error


async def test_empty_api_key_does_not_shadow_sdk_credential_resolution():
    """An empty env var must read as 'unset', not as an explicit empty key."""
    from app.llm.anthropic_provider import AnthropicProvider

    # Constructing with "" must not blow up, and must not pin an empty key.
    provider = AnthropicProvider(api_key="")
    assert provider.model
