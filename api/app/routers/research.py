"""Legacy research router (`/api/research`).

Provides compatibility endpoints for task management, approval gates, source vetoes,
and PDF downloads.
"""
from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.config import settings
from app.deps import CurrentUser, SessionDep
from app.models import ResearchTask, Source, TaskStatus, utcnow
from app.queue import enqueue
from app.schemas import (
    ApprovePlanRequest,
    CreateTaskRequest,
    TaskDetail,
    TaskOut,
    TaskSummary,
)

router = APIRouter(prefix="/api/research", tags=["research"])


async def _load_owned(session: SessionDep, task_id: str, user_id: str) -> ResearchTask:
    """Helper to fetch a task and verify user ownership.
    
    Returns 404 rather than 403 to avoid confirming the existence of other users' tasks.
    """
    task = await session.scalar(
        select(ResearchTask)
        .where(ResearchTask.id == task_id)
        .options(
            selectinload(ResearchTask.events), selectinload(ResearchTask.sources)
        )
    )
    if task is None or task.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )
    return task


@router.post("", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
async def create_task(
    body: CreateTaskRequest, session: SessionDep, user: CurrentUser
) -> ResearchTask:
    """Create a new research inquiry subject to daily user rate limits."""
    since = utcnow() - timedelta(days=1)
    recent = await session.scalar(
        select(func.count(ResearchTask.id)).where(
            ResearchTask.user_id == user.id, ResearchTask.created_at >= since
        )
    )
    if (recent or 0) >= settings.max_tasks_per_user_per_day:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Daily limit of {settings.max_tasks_per_user_per_day} research "
                "tasks reached. This cap exists to keep API spend bounded."
            ),
        )

    task = ResearchTask(user_id=user.id, query=body.query.strip())
    session.add(task)
    await session.commit()
    await session.refresh(task)

    await enqueue("plan_task", task.id)
    return task


@router.get("", response_model=list[TaskSummary])
async def list_tasks(session: SessionDep, user: CurrentUser) -> list[ResearchTask]:
    """List recent research tasks belonging to the authenticated user."""
    result = await session.scalars(
        select(ResearchTask)
        .where(ResearchTask.user_id == user.id)
        .order_by(ResearchTask.created_at.desc())
        .limit(100)
    )
    return list(result.all())


@router.get("/{task_id}", response_model=TaskDetail)
async def get_task(task_id: str, session: SessionDep, user: CurrentUser) -> ResearchTask:
    """Fetch complete task detail including events and retrieved sources."""
    return await _load_owned(session, task_id, user.id)


@router.post("/{task_id}/approve", response_model=TaskOut)
async def approve_plan(
    task_id: str, body: ApprovePlanRequest, session: SessionDep, user: CurrentUser
) -> ResearchTask:
    """Human approval gate: commits edited plan and dispatches research."""
    task = await _load_owned(session, task_id, user.id)
    if task.status != TaskStatus.AWAITING_APPROVAL:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Task is {task.status}, not awaiting approval",
        )

    edited = [step.strip() for step in body.plan if step.strip()]
    if not edited:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The plan cannot be empty",
        )

    task.plan_edited_by_user = edited != list(task.plan or [])
    task.plan = edited
    task.clarification_answers = {
        k: v for k, v in body.answers.items() if str(v).strip()
    }
    task.status = TaskStatus.QUEUED
    await session.commit()
    await session.refresh(task)

    await enqueue("run_task", task.id)
    return task


@router.post("/{task_id}/cancel", response_model=TaskOut)
async def cancel_task(
    task_id: str, session: SessionDep, user: CurrentUser
) -> ResearchTask:
    """Cancel an active or queued research task."""
    task = await _load_owned(session, task_id, user.id)
    if task.status in TaskStatus.TERMINAL:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Task is already {task.status}",
        )
    task.status = TaskStatus.CANCELLED
    await session.commit()
    await session.refresh(task)
    return task


@router.post("/{task_id}/sources/{source_id}/exclude", response_model=TaskDetail)
async def toggle_source(
    task_id: str,
    source_id: str,
    session: SessionDep,
    user: CurrentUser,
    excluded: bool = True,
) -> ResearchTask:
    """Toggle exclusion veto on a retrieved source."""
    task = await _load_owned(session, task_id, user.id)
    source = await session.get(Source, source_id)
    if source is None or source.task_id != task.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Source not found",
        )
    source.excluded = excluded
    await session.commit()
    await session.refresh(task)
    return task


@router.post("/{task_id}/share", response_model=TaskOut)
async def toggle_share(
    task_id: str, session: SessionDep, user: CurrentUser, public: bool = True
) -> ResearchTask:
    """Toggle public share accessibility for completed report."""
    task = await _load_owned(session, task_id, user.id)
    if task.status != TaskStatus.COMPLETE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only finished reports can be shared",
        )
    task.is_public = public
    if public and not task.share_id:
        task.share_id = uuid.uuid4().hex
    await session.commit()
    await session.refresh(task)
    return task


@router.get("/{task_id}/pdf")
async def download_pdf(task_id: str, session: SessionDep, user: CurrentUser) -> Response:
    """Download research report as a styled PDF binary."""
    from app.pdf import PDFUnavailable, render_report_pdf

    task = await _load_owned(session, task_id, user.id)
    if not task.report_markdown:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This task has no report yet",
        )
    try:
        pdf_bytes = render_report_pdf(task.query, task.report_markdown)
    except PDFUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    filename = f"report-{task.id[:8]}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

