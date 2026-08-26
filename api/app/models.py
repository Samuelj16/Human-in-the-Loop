"""Database models.

The task lifecycle is the heart of this app:

    queued -> planning -> awaiting_approval -> researching -> complete
                                |                   |
                                +--> cancelled <----+
                                        failed

`awaiting_approval` is the human-in-the-loop gate: the agent has drafted a plan
and (optionally) asked clarifying questions, and it will not spend another token
until a person edits/approves it.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    """Timezone-aware now(). Naive datetimes compare wrongly across DST and drivers."""
    return datetime.now(timezone.utc)


class TaskStatus(str):
    """The task state machine, as string constants.

    Deliberately not an Enum: these values are written to a plain string column
    and compared in SQL, and a bare str keeps queries and JSON payloads simple.
    """
    QUEUED = "queued"
    PLANNING = "planning"
    AWAITING_APPROVAL = "awaiting_approval"
    RESEARCHING = "researching"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"

    TERMINAL = {"complete", "failed", "cancelled"}


class User(Base):
    """An account. Everything a person creates hangs off this row."""
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    tasks: Mapped[list["ResearchTask"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class ResearchTask(Base):
    """One research request and everything known about it.

    Carries the plan awaiting approval, the finished report, the citation audit,
    and the running cost - so a single row answers 'what happened, and what did
    it cost'.
    """
    __tablename__ = "research_tasks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    query: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default=TaskStatus.QUEUED, index=True)

    # --- the human-in-the-loop payload ------------------------------------
    clarifying_questions: Mapped[list | None] = mapped_column(JSON, default=None)
    clarification_answers: Mapped[dict | None] = mapped_column(JSON, default=None)
    plan: Mapped[list | None] = mapped_column(JSON, default=None)  # list[str] of steps
    plan_edited_by_user: Mapped[bool] = mapped_column(Boolean, default=False)

    # --- output ------------------------------------------------------------
    report_markdown: Mapped[str | None] = mapped_column(Text, default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    share_id: Mapped[str | None] = mapped_column(String(32), unique=True, default=None)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)

    # --- accounting (spend caps read these) --------------------------------
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0)
    searches_used: Mapped[int] = mapped_column(Integer, default=0)
    # Shown on the approval gate before the person commits to the spend, and
    # compared against `actual_cost_usd` on the finished report.
    estimated_cost_usd: Mapped[float | None] = mapped_column(Float, default=None)
    actual_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    # Output of app.agent.citations.audit_citations - which cited URLs were
    # actually retrieved, and which the model invented.
    citation_report: Mapped[dict | None] = mapped_column(JSON, default=None)
    provider: Mapped[str | None] = mapped_column(String(32), default=None)
    model: Mapped[str | None] = mapped_column(String(64), default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    # Bumped by the worker while a run is alive. A task in a running state with
    # a stale heartbeat has lost its worker (redeploy, crash) and is reaped.
    heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    user: Mapped[User] = relationship(back_populates="tasks")
    events: Mapped[list["TaskEvent"]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="TaskEvent.created_at",
    )
    sources: Mapped[list["Source"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )
    turns: Mapped[list["LLMTurn"]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="LLMTurn.created_at",
    )


class TaskEvent(Base):
    """Append-only progress log. The UI polls these to render a live timeline."""

    __tablename__ = "task_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("research_tasks.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32))  # status | search | thought | error
    message: Mapped[str] = mapped_column(Text)
    data: Mapped[dict | None] = mapped_column(JSON, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # Monotonic per-task cursor so the UI can ask for "events after N" instead
    # of refetching the whole task on every poll.
    seq: Mapped[int] = mapped_column(Integer, default=0, index=True)

    task: Mapped[ResearchTask] = relationship(back_populates="events")

    __table_args__ = (Index("ix_task_events_task_seq", "task_id", "seq"),)


class Source(Base):
    """A page the agent actually read, kept so reports can cite and users can veto."""

    __tablename__ = "sources"
    __table_args__ = (UniqueConstraint("task_id", "url", name="uq_source_task_url"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("research_tasks.id", ondelete="CASCADE"), index=True
    )
    url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, default="")
    snippet: Mapped[str] = mapped_column(Text, default="")
    excluded: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    task: Mapped[ResearchTask] = relationship(back_populates="sources")


class LLMTurn(Base):
    """One model call. Makes a bad report debuggable and cost estimates tunable."""

    __tablename__ = "llm_turns"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("research_tasks.id", ondelete="CASCADE"), index=True
    )
    phase: Mapped[str] = mapped_column(String(16))  # planning | research | finalise
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(64))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    stop_reason: Mapped[str | None] = mapped_column(String(32), default=None)
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    task: Mapped[ResearchTask] = relationship(back_populates="turns")
