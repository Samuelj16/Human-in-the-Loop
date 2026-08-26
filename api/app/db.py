"""Async SQLAlchemy engine and session factory configuration.

This module sets up database infrastructure for the Human-in-the-Loop backend:
  - Base declarative class used by all ORM models and Alembic migrations.
  - Asynchronous SQLAlchemy engine configured with connection pre-ping.
  - Sessionmaker (`SessionLocal`) for scoped async database sessions.
  - Schema initialization helper (`init_db`) for fast local setup and testing.
  - FastAPI request-scoped session dependency (`get_session`).
"""
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings
from app.dburl import normalize_database_url


class Base(DeclarativeBase):
    """Declarative base shared by every model, and by Alembic's autogenerate.
    
    All database models inherit from this base to register table metadata.
    """
    pass


# Global asynchronous database engine.
# `pool_pre_ping=True` verifies connection liveness before checking out from the pool,
# preventing stale connection errors after idle timeouts or database restarts.
# Hosted providers hand out libpq-flavoured URLs; asyncpg needs them adjusted.
DATABASE_URL = normalize_database_url(settings.database_url)

engine = create_async_engine(DATABASE_URL, pool_pre_ping=True, future=True)

# Asynchronous session factory.
# `expire_on_commit=False` prevents attributes from being expired after commits,
# allowing models to be accessed safely in asynchronous request handlers after commit.
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    """Create tables if they do not exist.

    Alembic (`alembic upgrade head`) is authoritative - the container runs it on
    deploy. This exists so a fresh clone boots with one command, and it is
    disabled by AUTO_CREATE_SCHEMA=false wherever migrations are in charge.
    """
    if not settings.auto_create_schema:
        return

    # Import models dynamically to ensure all mapper metadata is registered with Base
    from app import models  # noqa: F401  (register mappers)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a request-scoped database session.

    Yields an AsyncSession instance and automatically closes it when the request ends.
    Background jobs deliberately do not use this - they open short sessions of
    their own so a slow model call never pins a connection.
    
    Yields:
        AsyncSession: An active database session for the duration of the HTTP request.
    """
    async with SessionLocal() as session:
        yield session

