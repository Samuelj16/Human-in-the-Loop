"""FastAPI application entrypoint and server lifecycle orchestration.

This module initializes the FastAPI web application, configures middleware,
attaches lifecycle handlers, and mounts API router endpoints:
  - Lifespan Manager: Initializes schema on startup, sweeps orphaned tasks from
    prior crashes, and conditionally starts an in-process sweeper task if Redis is unset.
  - CORS Middleware: Configured with origins from settings for seamless Next.js frontend communication.
  - Mounted Routers:
      * `/api/auth`: User registration, login, session inspection, and account deletion.
      * `/api/tasks`: Full task creation, polling, approval gate, and PDF export endpoints.
      * `/api/public`: Unauthenticated shared report retrieval.
  - Healthcheck & Status: Diagnostic endpoints reporting provider and worker topology.
"""
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
    """Application lifespan manager managing start-up and shut-down work.

    Reaps anything left running by a previous process, then - only when there is
    no arq worker to run it on a cron - starts the periodic sweep here.
    
    Args:
        app: The FastAPI application instance.
    """
    # 1. Initialize database schema if auto_create_schema is enabled
    await init_db()

    # 2. Anything left running from a previous process has lost its worker (reap it immediately)
    await reap_stale_tasks()

    # 3. With an arq worker, the reaper runs there on a cron. Without one, jobs
    # run in this process, so the sweep has to live here too.
    sweeper: asyncio.Task | None = None
    if not settings.redis_url:
        sweeper = asyncio.create_task(reaper_loop())

    try:
        yield
    finally:
        # Graceful shutdown: cancel in-process sweeper task
        if sweeper is not None:
            sweeper.cancel()
            await asyncio.gather(sweeper, return_exceptions=True)


# Instantiate FastAPI application
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

# Include route modules
app.include_router(auth.router)
app.include_router(tasks.router)
app.include_router(public.router)


@app.get("/", tags=["health"])
async def root() -> dict[str, str]:
    """Landing payload pointing at interactive API documentation."""
    return {"app": settings.app_name, "docs": "/docs", "status": "ok"}


@app.get("/health", tags=["health"])
@app.get("/api/health", tags=["health"])
async def health_check() -> dict[str, object]:
    """Deployment health check and wiring diagnostic.
    
    Reports active LLM provider, queue mode (Redis vs in-process), and search engine
    configuration. First point of inspection when diagnosing demo environments.
    """
    return {
        "status": "ok",
        "environment": settings.environment,
        "provider": settings.llm_provider,
        "queue": "redis" if settings.redis_url else "in-process",
        "search": "tavily" if settings.tavily_api_key else "stub",
    }

