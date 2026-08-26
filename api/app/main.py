"""FastAPI application entrypoint."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import init_db
from app.reaper import reap_stale_tasks, reaper_loop
from app.routers import auth, public, tasks

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize schema on startup
    """Start-up and shut-down work.

    Reaps anything left running by a previous process, then - only when there is
    no arq worker to run it on a cron - starts the periodic sweep here.
    """
    await init_db()

    # Anything left running from a previous process has lost its worker.
    await reap_stale_tasks()

    # With an arq worker, the reaper runs there on a cron. Without one, jobs
    # run in this process, so the sweep has to live here too.
    sweeper: asyncio.Task | None = None
    if not settings.redis_url:
        sweeper = asyncio.create_task(reaper_loop())

    try:
        yield
    finally:
        if sweeper is not None:
            sweeper.cancel()
            await asyncio.gather(sweeper, return_exceptions=True)


app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS middleware for Next.js frontend communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router)
app.include_router(tasks.router)
app.include_router(public.router)


@app.get("/", tags=["health"])
async def root() -> dict[str, str]:
    """Tiny landing payload pointing at the docs."""
    return {"app": settings.app_name, "docs": "/docs", "status": "ok"}


@app.get("/health", tags=["health"])
@app.get("/api/health", tags=["health"])
async def health_check() -> dict[str, object]:
    """Also reports how the deployment is wired, which is the first thing you
    want when a demo misbehaves."""
    return {
        "status": "ok",
        "environment": settings.environment,
        "provider": settings.llm_provider,
        "queue": "redis" if settings.redis_url else "in-process",
        "search": "tavily" if settings.tavily_api_key else "stub",
    }
