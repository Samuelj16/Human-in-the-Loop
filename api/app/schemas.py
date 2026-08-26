"""Request/response models for the HTTP API."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator


PlanStep = Annotated[str, Field(min_length=1, max_length=500)]
AnswerKey = Annotated[str, Field(min_length=1, max_length=200)]
AnswerValue = Annotated[str, Field(max_length=2000)]


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    email: str
    created_at: datetime


class CreateTaskRequest(BaseModel):
    query: str = Field(min_length=8, max_length=2000)


class ApprovePlanRequest(BaseModel):
    """The human's edits. `plan` replaces the agent's draft verbatim."""

    plan: list[PlanStep] = Field(min_length=1, max_length=12)
    answers: dict[AnswerKey, AnswerValue] = Field(
        default_factory=dict, max_length=12
    )

    @model_validator(mode="after")
    def limit_aggregate_prompt_input(self) -> "ApprovePlanRequest":
        size = sum(len(step.encode("utf-8")) for step in self.plan)
        size += sum(
            len(key.encode("utf-8")) + len(value.encode("utf-8"))
            for key, value in self.answers.items()
        )
        if size > 16_000:
            raise ValueError("Plan and answers must total at most 16000 UTF-8 bytes")
        return self


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    seq: int = 0
    kind: str
    message: str
    data: dict | None = None
    created_at: datetime


class SourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    url: str
    title: str
    snippet: str
    excluded: bool


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    query: str
    status: str
    clarifying_questions: list | None = None
    clarification_answers: dict | None = None
    plan: list | None = None
    plan_edited_by_user: bool = False
    report_markdown: str | None = None
    error: str | None = None
    share_id: str | None = None
    is_public: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    searches_used: int = 0
    # What approving this plan was predicted to cost, and what it actually cost.
    estimated_cost_usd: float | None = None
    actual_cost_usd: float = 0.0
    # Which cited URLs were genuinely retrieved (see app/agent/citations.py).
    citation_report: dict | None = None
    provider: str | None = None
    model: str | None = None
    created_at: datetime
    completed_at: datetime | None = None


class TaskDetail(TaskOut):
    events: list[EventOut] = Field(default_factory=list)
    sources: list[SourceOut] = Field(default_factory=list)


class TaskSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    query: str
    status: str
    created_at: datetime
    completed_at: datetime | None = None


class PublicReport(BaseModel):
    query: str
    report_markdown: str
    created_at: datetime
    sources: list[SourceOut] = Field(default_factory=list)


class EstimateRequest(BaseModel):
    """A candidate plan to price, so the number tracks the user's edits."""

    plan: list[PlanStep] = Field(min_length=1, max_length=12)


class EventsPage(BaseModel):
    """Incremental event feed, so polling does not resend the whole history."""

    task_id: str
    status: str
    cursor: int
    events: list[EventOut] = Field(default_factory=list)
    # Cheap fields the UI needs on every tick, without a full task refetch.
    searches_used: int = 0
    actual_cost_usd: float = 0.0
    done: bool = False


class CostEstimateOut(BaseModel):
    model: str
    expected_usd: float
    low_usd: float
    high_usd: float
    expected_searches: int
    expected_turns: int
    priced: bool
