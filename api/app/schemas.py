"""Request and response Pydantic models for the HTTP API.

Defines schemas for:
  - Authentication: Credentials, TokenResponse, UserOut
  - Task Lifecycle: CreateTaskRequest, ApprovePlanRequest, TaskOut, TaskDetail, TaskSummary
  - Incremental Telemetry: EventOut, EventsPage, SourceOut
  - Pre-flight Pricing & Cost Estimation: EstimateRequest, CostEstimateOut
  - Public Sharing: PublicReport
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

# Annotated validation types for plan steps and question answers
PlanStep = Annotated[str, Field(min_length=1, max_length=500, description="A single concrete research plan step")]
AnswerKey = Annotated[str, Field(min_length=1, max_length=200, description="Clarifying question prompt key")]
AnswerValue = Annotated[str, Field(max_length=2000, description="User response to clarifying question")]


class Credentials(BaseModel):
    """Email and password payload for user registration or authentication."""
    email: EmailStr = Field(description="User email address")
    password: str = Field(min_length=8, max_length=128, description="User password (min 8 chars)")


class TokenResponse(BaseModel):
    """A freshly issued JWT access token."""
    access_token: str = Field(description="Encoded JWT bearer token")
    token_type: str = Field(default="bearer", description="Token type descriptor")


class UserOut(BaseModel):
    """Public view of an authenticated user account."""
    model_config = ConfigDict(from_attributes=True)
    id: str = Field(description="Unique user identifier")
    email: str = Field(description="User email address")
    created_at: datetime = Field(description="Account creation timestamp")


class CreateTaskRequest(BaseModel):
    """Payload to initiate a new research inquiry."""
    query: str = Field(min_length=8, max_length=2000, description="Research question or topic")


class ApprovePlanRequest(BaseModel):
    """The human's edits submitted to the approval gate.
    
    `plan` replaces the agent's draft verbatim, and `answers` provides context
    for clarifying questions.
    """
    plan: list[PlanStep] = Field(min_length=1, max_length=12, description="Approved/edited research steps")
    answers: dict[AnswerKey, AnswerValue] = Field(
        default_factory=dict, max_length=12, description="Answers to clarifying questions"
    )

    @model_validator(mode="after")
    def limit_aggregate_prompt_input(self) -> "ApprovePlanRequest":
        """Cap total edited text, since all of it ends up in a model prompt.
        
        Prevents prompt injection or context exhaustion by bounding aggregate UTF-8 bytes to 16KB.
        """
        size = sum(len(step.encode("utf-8")) for step in self.plan)
        size += sum(
            len(key.encode("utf-8")) + len(value.encode("utf-8"))
            for key, value in self.answers.items()
        )
        if size > 16_000:
            raise ValueError("Plan and answers must total at most 16000 UTF-8 bytes")
        return self


class EventOut(BaseModel):
    """One progress event, carrying the `seq` cursor the UI polls with."""
    model_config = ConfigDict(from_attributes=True)
    id: str = Field(description="Unique event ID")
    seq: int = Field(default=0, description="Monotonic sequence number for polling cursors")
    kind: str = Field(description="Event kind: status, search, thought, error, warning")
    message: str = Field(description="Human-readable event message")
    data: dict | None = Field(default=None, description="Optional structured event payload")
    created_at: datetime = Field(description="Event timestamp")


class SourceOut(BaseModel):
    """A retrieved source, including whether the user vetoed it."""
    model_config = ConfigDict(from_attributes=True)
    id: str = Field(description="Unique source ID")
    url: str = Field(description="Retrieved page URL")
    title: str = Field(description="Page title")
    snippet: str = Field(description="Extracted content snippet")
    excluded: bool = Field(description="True if vetoed by the human researcher")


class TaskOut(BaseModel):
    """A task representation without nested full event and source lists."""
    model_config = ConfigDict(from_attributes=True)
    id: str = Field(description="Unique task ID")
    query: str = Field(description="Research question")
    status: str = Field(description="Current task status")
    clarifying_questions: list | None = Field(default=None, description="Planner-generated clarifying questions")
    clarification_answers: dict | None = Field(default=None, description="User-provided clarification answers")
    plan: list | None = Field(default=None, description="Research plan steps")
    plan_edited_by_user: bool = Field(default=False, description="Whether plan was modified before approval")
    report_markdown: str | None = Field(default=None, description="Final markdown research report")
    error: str | None = Field(default=None, description="Error message if failed")
    share_id: str | None = Field(default=None, description="Public share link identifier")
    is_public: bool = Field(default=False, description="Whether report is publicly viewable")
    input_tokens: int = Field(default=0, description="Fresh input tokens billed")
    output_tokens: int = Field(default=0, description="Output tokens billed")
    cache_read_tokens: int = Field(default=0, description="Cached input tokens read")
    cache_write_tokens: int = Field(default=0, description="Cached input tokens written")
    searches_used: int = Field(default=0, description="Web searches performed")
    # What approving this plan was predicted to cost, and what it actually cost.
    estimated_cost_usd: float | None = Field(default=None, description="Pre-flight expected dollar cost")
    actual_cost_usd: float = Field(default=0.0, description="Actual calculated dollar spend")
    # Which cited URLs were genuinely retrieved (see app/agent/citations.py).
    citation_report: dict | None = Field(default=None, description="Audit of cited vs retrieved URLs")
    provider: str | None = Field(default=None, description="LLM provider name")
    model: str | None = Field(default=None, description="LLM model identifier")
    created_at: datetime = Field(description="Task creation timestamp")
    completed_at: datetime | None = Field(default=None, description="Task completion timestamp")


class TaskDetail(TaskOut):
    """A task with its full event log and source ledger."""
    events: list[EventOut] = Field(default_factory=list, description="Ordered timeline events")
    sources: list[SourceOut] = Field(default_factory=list, description="Retrieved web sources")


class TaskSummary(BaseModel):
    """List-view fields only - kept small because the sidebar polls it."""
    model_config = ConfigDict(from_attributes=True)
    id: str = Field(description="Unique task ID")
    query: str = Field(description="Research query")
    status: str = Field(description="Task status")
    created_at: datetime = Field(description="Creation timestamp")
    completed_at: datetime | None = Field(default=None, description="Completion timestamp")


class PublicReport(BaseModel):
    """What a share link exposes: the report and its sources, and nothing else."""
    query: str = Field(description="Original research question")
    report_markdown: str = Field(description="Synthesized markdown report")
    created_at: datetime = Field(description="Publication timestamp")
    sources: list[SourceOut] = Field(default_factory=list, description="Active non-excluded references")


class EstimateRequest(BaseModel):
    """A candidate plan to price, so the number tracks the user's edits."""
    plan: list[PlanStep] = Field(min_length=1, max_length=12, description="Candidate plan steps to estimate")


class EventsPage(BaseModel):
    """Incremental event feed, so polling does not resend the whole history."""
    task_id: str = Field(description="Task ID")
    status: str = Field(description="Current task status")
    cursor: int = Field(description="Highest seq number in this page")
    events: list[EventOut] = Field(default_factory=list, description="New events after requested cursor")
    # Cheap fields the UI needs on every tick, without a full task refetch.
    searches_used: int = Field(default=0, description="Running search count")
    actual_cost_usd: float = Field(default=0.0, description="Running dollar spend")
    done: bool = Field(default=False, description="True if task reached terminal status")


class CostEstimateOut(BaseModel):
    """A priced plan, as shown on the approval gate."""
    model: str = Field(description="Model evaluated")
    expected_usd: float = Field(description="Expected dollar cost")
    low_usd: float = Field(description="Lower bound dollar cost")
    high_usd: float = Field(description="Upper bound dollar cost (spend cap ceiling)")
    expected_searches: int = Field(description="Projected number of searches")
    expected_turns: int = Field(description="Projected number of agent turns")
    priced: bool = Field(description="True if model pricing is verified from published list")

