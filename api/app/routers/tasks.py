"""Task lifecycle management endpoints."""
from __future__ import annotations

import uuid
from datetime import datetime, time, timezone

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import selectinload

from app.config import settings
from app.deps import CurrentUser, SessionDep
from app.models import ResearchTask, Source, TaskEvent, TaskStatus, utcnow
from app.pricing import estimate_task_cost
from app.queue import enqueue
from app.schemas import (
    ApprovePlanRequest,
    CostEstimateOut,
    CreateTaskRequest,
    EstimateRequest,
    EventOut,
    EventsPage,
    SourceOut,
    TaskDetail,
    TaskOut,
    TaskSummary,
)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.post("", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
async def create_task(
    body: CreateTaskRequest, user: CurrentUser, session: SessionDep
) -> ResearchTask:
    # SECURITY NOTE: This per-user count limits accidents, not adversarial spend.
    # Public deployments also need an atomic quota tied to a non-self-issued
    # tenant/billing entitlement; new accounts and concurrent requests can bypass
    # this count before paid planning work is enqueued below.
    """Create a research task and start plan drafting.

    Returns immediately; the plan is drafted in the background and the task lands
    in `awaiting_approval`. Subject to the per-user daily cap.
    """
    today_start = datetime.combine(
        datetime.now(timezone.utc).date(), time.min, tzinfo=timezone.utc
    )
    count_today = await session.scalar(
        select(func.count(ResearchTask.id)).where(
            ResearchTask.user_id == user.id,
            ResearchTask.created_at >= today_start,
        )
    )
    if (count_today or 0) >= settings.max_tasks_per_user_per_day:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Daily limit of {settings.max_tasks_per_user_per_day} tasks reached.",
        )

    task = ResearchTask(
        user_id=user.id,
        query=body.query.strip(),
        status=TaskStatus.QUEUED,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)

    await enqueue("plan_task", task.id)
    return task


@router.get("", response_model=list[TaskSummary])
async def list_tasks(user: CurrentUser, session: SessionDep) -> list[ResearchTask]:
    """List this user's tasks, newest first."""
    result = await session.scalars(
        select(ResearchTask)
        .where(ResearchTask.user_id == user.id)
        .order_by(ResearchTask.created_at.desc())
    )
    return list(result.all())


@router.get("/{task_id}", response_model=TaskDetail)
async def get_task(
    task_id: str, user: CurrentUser, session: SessionDep
) -> ResearchTask:
    """Full task detail: plan, events, sources, and the citation audit.

    Prefer `/events?after=N` while a run is in flight - this returns the entire
    history every time.
    """
    result = await session.scalars(
        select(ResearchTask)
        .where(ResearchTask.id == task_id, ResearchTask.user_id == user.id)
        .options(
            selectinload(ResearchTask.events),
            selectinload(ResearchTask.sources),
        )
    )
    task = result.first()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.post("/{task_id}/approve", response_model=TaskOut)
async def approve_plan(
    task_id: str,
    body: ApprovePlanRequest,
    user: CurrentUser,
    session: SessionDep,
) -> ResearchTask:
    """Approve a drafted plan and start the research run.

    The gate: this is the call that authorises spending money, so the status
    check is only advisory and the real transition is a conditional UPDATE the
    database arbitrates. Two concurrent clicks cannot buy two runs.
    """
    task = await session.get(ResearchTask, task_id)
    if task is None or task.user_id != user.id:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status != TaskStatus.AWAITING_APPROVAL:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot approve task in status {task.status!r}",
        )

    clean_plan = [s.strip() for s in body.plan if s.strip()]
    if not clean_plan:
        raise HTTPException(
            status_code=422,
            detail="The plan must contain at least one step.",
        )

    # This is the gate that authorises spending money, so the status check above
    # is only advisory - two clients can both pass it. The transition itself is
    # done as a conditional UPDATE, and the database decides who wins. The loser
    # gets a 409 instead of silently enqueueing a second, duplicate research run.
    result = await session.execute(
        update(ResearchTask)
        .where(
            ResearchTask.id == task_id,
            ResearchTask.status == TaskStatus.AWAITING_APPROVAL,
        )
        .values(
            plan=clean_plan,
            plan_edited_by_user=task.plan != clean_plan,
            clarification_answers=body.answers,
            status=TaskStatus.RESEARCHING,
            updated_at=utcnow(),
        )
        .returning(ResearchTask.id)
        .execution_options(synchronize_session=False)
    )
    if result.scalar_one_or_none() is None:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This plan was already approved.",
        )

    await session.commit()
    await session.refresh(task)

    # Enqueued only after the winning transition is durable.
    await enqueue("run_task", task.id)
    return task


@router.post("/{task_id}/cancel", response_model=TaskOut)
async def cancel_task(
    task_id: str, user: CurrentUser, session: SessionDep
) -> ResearchTask:
    """Cancel a task. The agent loop checks between turns and stops."""
    task = await session.get(ResearchTask, task_id)
    if task is None or task.user_id != user.id:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status not in TaskStatus.TERMINAL:
        task.status = TaskStatus.CANCELLED
        task.updated_at = utcnow()
        await session.commit()
        await session.refresh(task)

    return task


@router.post("/{task_id}/sources/{source_id}/toggle", response_model=SourceOut)
async def toggle_source_exclusion(
    task_id: str,
    source_id: str,
    user: CurrentUser,
    session: SessionDep,
) -> Source:
    """Veto (or un-veto) a source, excluding it from later runs."""
    task = await session.get(ResearchTask, task_id)
    if task is None or task.user_id != user.id:
        raise HTTPException(status_code=404, detail="Task not found")

    source = await session.scalar(
        select(Source).where(Source.id == source_id, Source.task_id == task_id)
    )
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")

    source.excluded = not source.excluded
    await session.commit()
    await session.refresh(source)
    return source


@router.post("/{task_id}/share", response_model=TaskOut)
async def toggle_share(
    task_id: str, user: CurrentUser, session: SessionDep
) -> ResearchTask:
    """Toggle the public share link for a finished report."""
    task = await session.get(ResearchTask, task_id)
    if task is None or task.user_id != user.id:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status != TaskStatus.COMPLETE:
        raise HTTPException(
            status_code=409, detail="Only finished reports can be shared"
        )

    task.is_public = not task.is_public
    if task.is_public and not task.share_id:
        task.share_id = uuid.uuid4().hex
    task.updated_at = utcnow()

    await session.commit()
    await session.refresh(task)
    return task



@router.get("/{task_id}/events", response_model=EventsPage)
async def get_events(
    task_id: str,
    user: CurrentUser,
    session: SessionDep,
    after: int = Query(0, ge=0, description="Return events with seq greater than this"),
    limit: int = Query(200, ge=1, le=500),
) -> EventsPage:
    """Incremental progress feed.

    Polling the full task resends every event and source on every tick, so the
    payload grows with the run. This returns only what the client has not seen,
    which keeps a long research run's polling cost flat.
    """
    task = await session.get(ResearchTask, task_id)
    if task is None or task.user_id != user.id:
        raise HTTPException(status_code=404, detail="Task not found")

    rows = list(
        (
            await session.scalars(
                select(TaskEvent)
                .where(TaskEvent.task_id == task_id, TaskEvent.seq > after)
                .order_by(TaskEvent.seq)
                .limit(limit)
            )
        ).all()
    )
    events = [EventOut.model_validate(row) for row in rows]

    return EventsPage(
        task_id=task.id,
        status=task.status,
        cursor=events[-1].seq if events else after,
        events=events,
        searches_used=task.searches_used,
        actual_cost_usd=task.actual_cost_usd,
        done=task.status in TaskStatus.TERMINAL,
    )


@router.get("/{task_id}/estimate", response_model=CostEstimateOut)
async def get_estimate(
    task_id: str,
    user: CurrentUser,
    session: SessionDep,
) -> CostEstimateOut:
    """What the current plan would cost to run - recomputed on the fly so the
    number responds to the user's edits before they approve."""
    task = await session.get(ResearchTask, task_id)
    if task is None or task.user_id != user.id:
        raise HTTPException(status_code=404, detail="Task not found")

    estimate = estimate_task_cost(
        list(task.plan or []),
        model=task.model or settings.anthropic_model,
        max_searches=settings.max_searches_per_task,
        max_iterations=settings.max_tool_iterations,
    )
    return CostEstimateOut(**estimate.as_dict())


@router.post("/{task_id}/estimate", response_model=CostEstimateOut)
async def estimate_candidate_plan(
    task_id: str,
    body: EstimateRequest,
    user: CurrentUser,
    session: SessionDep,
) -> CostEstimateOut:
    """Price a plan the user is still editing, before they commit to it."""
    task = await session.get(ResearchTask, task_id)
    if task is None or task.user_id != user.id:
        raise HTTPException(status_code=404, detail="Task not found")

    estimate = estimate_task_cost(
        [step.strip() for step in body.plan if step.strip()],
        model=task.model or settings.anthropic_model,
        max_searches=settings.max_searches_per_task,
        max_iterations=settings.max_tool_iterations,
    )
    return CostEstimateOut(**estimate.as_dict())


@router.get("/{task_id}/pdf")
async def download_pdf(
    task_id: str, user: CurrentUser, session: SessionDep
) -> Response:
    """Render the finished report as a PDF attachment.

    Returns 503 when the image lacks WeasyPrint's system libraries, rather than
    failing at boot.
    """
    from app.pdf import PDFUnavailable, render_report_pdf

    task = await session.get(ResearchTask, task_id)
    if task is None or task.user_id != user.id:
        raise HTTPException(status_code=404, detail="Task not found")
    if not task.report_markdown:
        raise HTTPException(status_code=409, detail="This task has no report yet")

    try:
        pdf_bytes = render_report_pdf(task.query, task.report_markdown)
    except PDFUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="report-{task.id[:8]}.pdf"'
        },
    )
