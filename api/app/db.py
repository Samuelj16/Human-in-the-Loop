"""Async SQLAlchemy engine + session factory."""
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    """Create tables if they do not exist.

    Alembic (`alembic upgrade head`) is authoritative - the container runs it on
    deploy. This exists so a fresh clone boots with one command, and it is
    disabled by AUTO_CREATE_SCHEMA=false wherever migrations are in charge.
    """
    if not settings.auto_create_schema:
        return

    from app import models  # noqa: F401  (register mappers)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
