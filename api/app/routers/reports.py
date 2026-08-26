"""Public report retrieval router (`/api/reports`).

Provides unauthenticated read-only endpoint for shared research reports.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.deps import SessionDep
from app.models import ResearchTask, TaskStatus
from app.schemas import PublicReport, SourceOut

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("/{share_id}", response_model=PublicReport)
async def get_public_report(share_id: str, session: SessionDep) -> PublicReport:
    """Fetch a public research report by share ID.
    
    Args:
        share_id: Unique public sharing UUID.
        session: Scoped database session.
        
    Returns:
        PublicReport: Rendered markdown report and active source citations.
        
    Raises:
        HTTPException (404): If report does not exist, is private, or has not completed.
    """
    task = await session.scalar(
        select(ResearchTask)
        .where(ResearchTask.share_id == share_id)
        .options(selectinload(ResearchTask.sources))
    )
    if (
        task is None
        or not task.is_public
        or task.status != TaskStatus.COMPLETE
        or not task.report_markdown
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report not found",
        )

    return PublicReport(
        query=task.query,
        report_markdown=task.report_markdown,
        created_at=task.created_at,
        sources=[
            SourceOut.model_validate(s) for s in task.sources if not s.excluded
        ],
    )

