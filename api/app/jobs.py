"""Background jobs: plan drafting and plan execution.

Each job owns its own short-lived DB sessions. The research loop can run for
minutes, so it must never hold a transaction open while waiting on the model -
progress hooks open, write, and close.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import func, select

from app.agent import AgentHooks, Budget, ResearchOutcome, draft_plan, run_research
from app.agent.citations import audit_citations
from app.config import settings
from app.db import SessionLocal
from app.llm import LLMError, get_llm_provider
from app.llm.base import LLMResponse
from app.models import LLMTurn, ResearchTask, Source, TaskEvent, TaskStatus, utcnow
from app.pricing import cost_usd, estimate_task_cost
from app.search import get_search_client
from app.search.base import SearchResult

log = logging.getLogger(__name__)


async def _add_event(task_id: str, kind: str, message: str, data: dict | None = None):
    """Append a progress event with a monotonic per-task cursor.

    A task is only ever worked by one job at a time, so reading the current max
    and adding one is safe here; the index on (task_id, seq) makes the read cheap.
    """
    async with SessionLocal() as session:
        next_seq = await session.scalar(
            select(func.coalesce(func.max(TaskEvent.seq), 0) + 1).where(
                TaskEvent.task_id == task_id
            )
        )
        session.add(
            TaskEvent(
                task_id=task_id,
                kind=kind,
                message=message[:4000],
                data=data,
                seq=next_seq or 1,
            )
        )
        await session.commit()


async def _set_status(task_id: str, status: str, **fields: Any) -> None:
    async with SessionLocal() as session:
        task = await session.get(ResearchTask, task_id)
        if task is None:
            return
        task.status = status
        for key, value in fields.items():
            setattr(task, key, value)
        await session.commit()


async def _touch_heartbeat(task_id: str) -> None:
    """Prove the worker is still alive so the reaper leaves this task alone."""
    async with SessionLocal() as session:
        task = await session.get(ResearchTask, task_id)
        if task is not None:
            task.heartbeat_at = utcnow()
            await session.commit()


async def _is_cancelled(task_id: str) -> bool:
    async with SessionLocal() as session:
        task = await session.get(ResearchTask, task_id)
        return task is None or task.status == TaskStatus.CANCELLED


async def _record_source(task_id: str, result: SearchResult) -> None:
    async with SessionLocal() as session:
        exists = await session.scalar(
            select(Source.id).where(Source.task_id == task_id, Source.url == result.url)
        )
        if exists:
            return
        session.add(
            Source(
                task_id=task_id,
                url=result.url,
                title=result.title[:500],
                snippet=result.snippet[:1000],
            )
        )
        await session.commit()


async def _record_turn(
    task_id: str, phase: str, provider_name: str, response: LLMResponse
) -> None:
    """Persist one model call: tokens, dollars, latency, retries.

    Without this a disappointing report is unexplainable after the fact, and the
    cost estimates in app/pricing.py can never be calibrated against reality.
    """
    usage = response.usage
    async with SessionLocal() as session:
        session.add(
            LLMTurn(
                task_id=task_id,
                phase=phase,
                provider=provider_name,
                model=response.model or "unknown",
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_read_tokens=usage.cache_read_tokens,
                cache_write_tokens=usage.cache_write_tokens,
                cost_usd=cost_usd(
                    response.model,
                    usage.input_tokens,
                    usage.output_tokens,
                    usage.cache_read_tokens,
                    usage.cache_write_tokens,
                ),
                latency_ms=response.latency_ms,
                tool_calls=len(response.tool_calls),
                stop_reason=response.stop_reason,
                attempts=response.attempts,
            )
        )
        await session.commit()


async def _accumulate(task_id: str, response: LLMResponse) -> None:
    """Roll one turn's usage into the task's running totals."""
    usage = response.usage
    async with SessionLocal() as session:
        task = await session.get(ResearchTask, task_id)
        if task is None:
            return
        task.input_tokens += usage.input_tokens
        task.output_tokens += usage.output_tokens
        task.cache_read_tokens += usage.cache_read_tokens
        task.cache_write_tokens += usage.cache_write_tokens
        task.actual_cost_usd = round(
            task.actual_cost_usd
            + cost_usd(
                response.model,
                usage.input_tokens,
                usage.output_tokens,
                usage.cache_read_tokens,
                usage.cache_write_tokens,
            ),
            6,
        )
        task.heartbeat_at = utcnow()
        await session.commit()


# --------------------------------------------------------------------------
# Job 1 - draft the plan, price it, then stop and wait for a human
# --------------------------------------------------------------------------
async def plan_task(ctx: dict | None, task_id: str) -> None:
    """Draft a plan, price it, then stop and wait for a human.

    Ends in `awaiting_approval` with a cost estimate attached. Every failure path
    writes a status: a background job that dies silently leaves the UI spinning
    with nothing behind it.
    """
    async with SessionLocal() as session:
        task = await session.get(ResearchTask, task_id)
        if task is None or task.status == TaskStatus.CANCELLED:
            return
        query = task.query

    try:
        provider = get_llm_provider()
    except Exception as exc:  # noqa: BLE001 - misconfiguration must be visible
        log.exception("could not build an LLM provider for %s", task_id)
        await _add_event(task_id, "error", str(exc))
        await _set_status(task_id, TaskStatus.FAILED, error=str(exc))
        return

    await _set_status(
        task_id,
        TaskStatus.PLANNING,
        provider=provider.name,
        model=provider.model,
        heartbeat_at=utcnow(),
    )
    await _add_event(task_id, "status", "Drafting a research plan for your review.")

    try:
        plan, response = await draft_plan(query, provider)
    except LLMError as exc:
        log.exception("planning failed for %s", task_id)
        await _add_event(task_id, "error", str(exc))
        await _set_status(task_id, TaskStatus.FAILED, error=str(exc))
        return
    except Exception as exc:  # noqa: BLE001 - nothing may leave a task wedged
        log.exception("unexpected planning failure for %s", task_id)
        await _add_event(task_id, "error", f"Unexpected failure: {exc}")
        await _set_status(task_id, TaskStatus.FAILED, error=str(exc))
        return

    await _record_turn(task_id, "planning", provider.name, response)
    await _accumulate(task_id, response)

    # Price the plan before anyone is asked to approve it.
    estimate = estimate_task_cost(
        plan.plan,
        model=provider.model,
        max_searches=settings.max_searches_per_task,
        max_iterations=settings.max_tool_iterations,
    )

    await _set_status(
        task_id,
        TaskStatus.AWAITING_APPROVAL,
        plan=plan.plan,
        clarifying_questions=plan.clarifying_questions,
        estimated_cost_usd=estimate.expected_usd,
    )
    await _add_event(
        task_id,
        "status",
        f"Plan ready - about ${estimate.expected_usd:.2f} to run. "
        "Nothing more is spent until you approve it.",
        {"restated_question": plan.restated_question, "estimate": estimate.as_dict()},
    )


# --------------------------------------------------------------------------
# Job 2 - run the approved plan
# --------------------------------------------------------------------------
async def run_task(ctx: dict | None, task_id: str) -> None:
    """Execute an approved plan and audit the resulting report.

    Runs the agent loop, streams progress into task_events, records per-turn
    telemetry, then checks every citation against the sources actually retrieved
    before marking the task complete.
    """
    async with SessionLocal() as session:
        task = await session.get(ResearchTask, task_id)
        if task is None or task.status == TaskStatus.CANCELLED:
            return
        query, plan = task.query, list(task.plan or [])
        answers = dict(task.clarification_answers or {})
        excluded = set(
            (
                await session.scalars(
                    select(Source.url).where(
                        Source.task_id == task_id, Source.excluded.is_(True)
                    )
                )
            ).all()
        )

    provider = get_llm_provider()
    search = get_search_client()
    budget = Budget(
        max_iterations=settings.max_tool_iterations,
        max_searches=settings.max_searches_per_task,
        max_output_tokens=settings.max_output_tokens_per_task,
    )

    await _set_status(task_id, TaskStatus.RESEARCHING, heartbeat_at=utcnow())
    await _add_event(
        task_id,
        "status",
        f"Researching with {provider.name}/{provider.model} "
        f"(cap: {budget.max_searches} searches, {budget.max_iterations} turns).",
    )

    async def on_turn(phase: str, response: LLMResponse) -> None:
        """Persist one model call and roll it into the task totals."""
        await _record_turn(task_id, phase, provider.name, response)
        await _accumulate(task_id, response)

    hooks = AgentHooks(
        on_event=lambda kind, message, data=None: _add_event(
            task_id, kind, message, data
        ),
        on_source=lambda result: _record_source(task_id, result),
        should_cancel=lambda: _is_cancelled(task_id),
        on_turn=on_turn,
    )

    try:
        outcome: ResearchOutcome = await run_research(
            query=query,
            plan=plan,
            answers=answers,
            provider=provider,
            search=search,
            budget=budget,
            hooks=hooks,
            excluded_urls=excluded,
        )
    except LLMError as exc:
        log.exception("research failed for %s", task_id)
        await _add_event(task_id, "error", str(exc))
        await _set_status(task_id, TaskStatus.FAILED, error=str(exc))
        return
    except Exception as exc:  # noqa: BLE001 - a crashed worker must not wedge a task
        log.exception("unexpected research failure for %s", task_id)
        await _add_event(task_id, "error", f"Unexpected failure: {exc}")
        await _set_status(task_id, TaskStatus.FAILED, error=str(exc))
        return

    if outcome.stopped_reason == "cancelled":
        await _set_status(task_id, TaskStatus.CANCELLED)
        return

    # Check the report's citations against what was actually retrieved.
    async with SessionLocal() as session:
        retrieved = list(
            (
                await session.scalars(
                    select(Source.url).where(Source.task_id == task_id)
                )
            ).all()
        )
    audit = audit_citations(outcome.report_markdown, retrieved)
    if audit.unverified:
        await _add_event(
            task_id,
            "warning",
            f"{len(audit.unverified)} cited link(s) were never retrieved by a "
            "search and are flagged as unverified.",
            {"unverified": audit.unverified},
        )

    await _set_status(
        task_id,
        TaskStatus.COMPLETE,
        report_markdown=outcome.report_markdown,
        share_id=uuid.uuid4().hex,
        searches_used=outcome.searches_used,
        citation_report=audit.as_dict(),
        completed_at=utcnow(),
        heartbeat_at=None,
    )
