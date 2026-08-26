"""Public shared report endpoint (`/api/public`).

Exposes unauthenticated viewing for finished reports that have `is_public == True`:
  - Does not leak unfinished or private task existence (returns 404).
  - Excludes vetoed sources (`excluded == True`) from the public reference list.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.deps import SessionDep
from app.models import ResearchTask, TaskStatus
from app.schemas import PublicReport, SourceOut

router = APIRouter(prefix="/api/public", tags=["public"])


@router.get("/reports/{share_id}", response_model=PublicReport)
async def get_public_report(share_id: str, session: SessionDep) -> PublicReport:
    """Fetch a publicly shared report by its unique share UUID.

    Unauthenticated by design, so public links work without login.
    Returns 404 rather than 403 for private or unfinished tasks to prevent
    information leakage regarding the existence of private share IDs.
    
    Args:
        share_id: 32-character hexadecimal share link identifier.
        session: Scoped database session.
        
    Returns:
        PublicReport: Rendered markdown report and active non-excluded source references.
        
    Raises:
        HTTPException (404): If report does not exist, is private, or has not completed.
    """
    result = await session.scalars(
        select(ResearchTask)
        .where(
            ResearchTask.share_id == share_id,
            ResearchTask.is_public.is_(True),
            ResearchTask.status == TaskStatus.COMPLETE,
        )
        .options(selectinload(ResearchTask.sources))
    )
    task = result.first()
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report not found or not public.",
        )

    # Return only active (non-vetoed) sources
    sources = [
        SourceOut.model_validate(s) for s in task.sources if not s.excluded
    ]
    return PublicReport(
        query=task.query,
        report_markdown=task.report_markdown or "",
        created_at=task.created_at,
        sources=sources,
    )


