"""Task lifecycle router (`/api/tasks`).

End-to-end task execution workflow:
  1. `POST /api/tasks`: Create inquiry, check per-user daily quota, enqueue `plan_task`.
  2. `GET /api/tasks`: List user's tasks ordered by timestamp descending.
  3. `GET /api/tasks/{task_id}`: Full task detail with timeline events, sources, and citation audit.
  4. `POST /api/tasks/{task_id}/approve`: Concurrency-safe plan approval gate with atomic SQL UPDATE.
  5. `POST /api/tasks/{task_id}/cancel`: User cancellation trigger between agent turns.
  6. `POST /api/tasks/{task_id}/sources/{source_id}/toggle`: Source exclusion veto toggle.
  7. `POST /api/tasks/{task_id}/share`: Toggle public sharing URL.
  8. `GET /api/tasks/{task_id}/events`: Monotonic cursor polling (`?after={seq}`) for low-bandwidth telemetry.
  9. `GET / POST /api/tasks/{task_id}/estimate`: Dynamic pre-flight pricing calculations.
  10. `GET /api/tasks/{task_id}/pdf`: WeasyPrint PDF report generation and binary download.
"""
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
    """Create a research task and start plan drafting in the background.

    Returns immediately; the plan is drafted asynchronously and the task lands
    in `awaiting_approval`. Subject to the per-user daily quota cap.
    
    Args:
        body: Inquiry question payload.
        user: Authenticated user dependency.
        session: Scoped database session.
        
    Returns:
        ResearchTask: Newly created task record in QUEUED status.
        
    Raises:
        HTTPException (429): If the user exceeded max_tasks_per_user_per_day.
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
    """List this user's tasks, ordered newest first for sidebar display.
    
    Args:
        user: Authenticated user.
        session: Database session.
        
    Returns:
        list[ResearchTask]: User's task summaries.
    """
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
    """Full task detail including plan, events, sources, and the citation audit.

    Prefer `/events?after=N` while a run is in flight - this returns the entire
    history on every fetch.
    
    Args:
        task_id: Target task ID.
        user: Authenticated user.
        session: Database session.
        
    Returns:
        ResearchTask: Detailed task object with eagerly loaded relationships.
        
    Raises:
        HTTPException (404): If task does not exist or belongs to another user.
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
    """Approve a drafted plan and dispatch the autonomous research loop.

    The gate: this call authorises spending money, so the status check is only
    advisory and the real state transition is an atomic conditional UPDATE the
    database arbitrates. Two concurrent clicks cannot buy two runs.
    
    Args:
        task_id: Task ID to approve.
        body: Approved/edited plan steps and clarification answers.
        user: Authenticated user.
        session: Database session.
        
    Returns:
        ResearchTask: Task transitioned to RESEARCHING.
        
    Raises:
        HTTPException (404): If task not found.
        HTTPException (400): If status is not awaiting_approval.
        HTTPException (409): If plan was already approved by a concurrent request.
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

    # Concurrency Protection: Conditional UPDATE WHERE status = 'awaiting_approval'.
    # Database guarantees exactly one caller succeeds; loser gets 409 Conflict.
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

    # Enqueued only after winning database transition is durable
    await enqueue("run_task", task.id)
    return task


@router.post("/{task_id}/cancel", response_model=TaskOut)
async def cancel_task(
    task_id: str, user: CurrentUser, session: SessionDep
) -> ResearchTask:
    """Cancel a running or queued task. The agent loop checks cancellation between turns and halts.
    
    Args:
        task_id: Task ID to cancel.
        user: Authenticated user.
        session: Database session.
        
    Returns:
        ResearchTask: Updated task record.
    """
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
    """Veto (or un-veto) a retrieved source, excluding it from prompting and citation credit.
    
    Args:
        task_id: Associated research task ID.
        source_id: Unique source identifier.
        user: Authenticated user.
        session: Database session.
        
    Returns:
        Source: Updated Source record.
    """
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
    """Toggle public sharing visibility and generate share link UUID for finished reports.
    
    Args:
        task_id: Research task ID.
        user: Authenticated user.
        session: Database session.
        
    Returns:
        ResearchTask: Updated task with share_id and is_public flag.
    """
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
    after: int = Query(0, ge=0, description="Return events with seq greater than this cursor"),
    limit: int = Query(200, ge=1, le=500),
) -> EventsPage:
    """Incremental progress feed using monotonic sequence cursors.

    Polling the full task resends every event and source on every tick, so the
    payload grows with the run. This returns only what the client has not seen,
    which keeps a long research run's polling bandwidth flat.
    
    Args:
        task_id: Target task ID.
        user: Authenticated user.
        session: Database session.
        after: Sequence cursor offset.
        limit: Max events per chunk.
        
    Returns:
        EventsPage: Page of new events and running telemetry counters.
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
    """Recompute projected dollar cost for the current drafted plan in real-time.
    
    Args:
        task_id: Research task ID.
        user: Authenticated user.
        session: Database session.
        
    Returns:
        CostEstimateOut: Calculated dollar cost bounds and projections.
    """
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
    """Price a candidate plan currently being edited by the user in the UI before committing.
    
    Args:
        task_id: Research task ID.
        body: Candidate plan steps list.
        user: Authenticated user.
        session: Database session.
        
    Returns:
        CostEstimateOut: Price estimate for candidate plan.
    """
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
    
    Args:
        task_id: Research task ID.
        user: Authenticated user.
        session: Database session.
        
    Returns:
        Response: Binary PDF stream with Content-Disposition attachment header.
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

