"""Public report endpoints (unauthenticated)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.deps import SessionDep
from app.models import ResearchTask, Source, TaskStatus
from app.schemas import PublicReport, SourceOut

router = APIRouter(prefix="/api/public", tags=["public"])


@router.get("/reports/{share_id}", response_model=PublicReport)
async def get_public_report(share_id: str, session: SessionDep) -> PublicReport:
    """Fetch a shared report by share id.

    Unauthenticated by design, so a link works for someone with no account.
    Returns 404 rather than 403 for private or unfinished reports, so the
    endpoint never confirms that a given share id exists.
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
        raise HTTPException(status_code=404, detail="Report not found or not public")

    sources = [
        SourceOut.model_validate(s) for s in task.sources if not s.excluded
    ]
    return PublicReport(
        query=task.query,
        report_markdown=task.report_markdown or "",
        created_at=task.created_at,
        sources=sources,
    )

