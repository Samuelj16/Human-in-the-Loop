"""The research agent: a hand-written tool-use loop.

Written by hand rather than pulled from a framework because the interesting
parts of this project *are* the loop - the human approval gate, the spend caps,
the cancellation checks, and the source ledger. A framework would hide exactly
the code worth showing.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.agent.prompts import FINALISE_NUDGE, PLANNER_SYSTEM, RESEARCHER_SYSTEM
from app.llm.base import (
    LLMError,
    LLMProvider,
    LLMResponse,
    Message,
    ToolSpec,
    Usage,
    tool_result_message,
    user_message,
)
from app.search.base import SearchClient, SearchResult

log = logging.getLogger(__name__)

SEARCH_TOOL = ToolSpec(
    name="web_search",
    description=(
        "Search the public web and return the top results with short extracts. "
        "Use one focused question or phrase per call."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query. Be specific and self-contained.",
            }
        },
        "required": ["query"],
        "additionalProperties": False,
    },
)


# The planner's output is constrained to this schema by the provider, so the
# response needs no parsing and cannot arrive malformed.
PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "restated_question": {
            "type": "string",
            "description": "One sentence restating the question as understood.",
        },
        "clarifying_questions": {
            "type": "array",
            "description": "0-3 questions, only where an answer changes the research.",
            "items": {"type": "string"},
            "maxItems": 3,
        },
        "plan": {
            "type": "array",
            "description": "3-6 concrete research steps, each phrased as an action.",
            "items": {"type": "string"},
            "minItems": 1,
            "maxItems": 6,
        },
    },
    "required": ["restated_question", "clarifying_questions", "plan"],
    "additionalProperties": False,
}


# --------------------------------------------------------------------------
# Budget
# --------------------------------------------------------------------------
@dataclass
class Budget:
    """Hard caps. Without these a public demo link is an open tab at the bar."""

    max_iterations: int = 12
    max_searches: int = 8
    max_output_tokens: int = 60_000

    iterations_used: int = 0
    searches_used: int = 0
    usage: Usage = field(default_factory=Usage)

    def record(self, usage: Usage) -> None:
        """Fold one call's usage into the running total."""
        self.usage = self.usage + usage

    @property
    def searches_left(self) -> int:
        """Searches still permitted by the cap."""
        return max(0, self.max_searches - self.searches_used)

    def exhausted_reason(self) -> str | None:
        """Why the run must stop, or None if it may continue."""
        if self.iterations_used >= self.max_iterations:
            return f"turn limit of {self.max_iterations} reached"
        if self.searches_used >= self.max_searches:
            return f"search limit of {self.max_searches} reached"
        if self.usage.output_tokens >= self.max_output_tokens:
            return f"output token limit of {self.max_output_tokens} reached"
        return None


# --------------------------------------------------------------------------
# Hooks the caller (worker) supplies to persist progress and allow cancelling
# --------------------------------------------------------------------------
EventFn = Callable[[str, str, dict[str, Any] | None], Awaitable[None]]
SourceFn = Callable[[SearchResult], Awaitable[None]]
CancelFn = Callable[[], Awaitable[bool]]
TurnFn = Callable[[str, LLMResponse], Awaitable[None]]


async def _noop_event(kind: str, message: str, data: dict | None = None) -> None:
    return None


async def _noop_source(result: SearchResult) -> None:
    return None


async def _never_cancel() -> bool:
    return False


async def _noop_turn(phase: str, response: LLMResponse) -> None:
    return None


@dataclass
class AgentHooks:
    """Callbacks the caller supplies to persist progress and allow cancelling.

    The loop stays free of database code; the job layer decides what to store.
    """
    on_event: EventFn = _noop_event
    on_source: SourceFn = _noop_source
    should_cancel: CancelFn = _never_cancel
    on_turn: TurnFn = _noop_turn


@dataclass
class ResearchPlan:
    """A drafted plan awaiting human approval."""
    plan: list[str]
    clarifying_questions: list[str] = field(default_factory=list)
    restated_question: str = ""


@dataclass
class ResearchOutcome:
    """The finished run: the report, what it cost, and why it stopped."""
    report_markdown: str
    usage: Usage
    searches_used: int
    stopped_reason: str  # completed | budget | cancelled


# --------------------------------------------------------------------------
# Phase 1: draft a plan for a human to approve
# --------------------------------------------------------------------------
def _extract_json(text: str) -> dict[str, Any]:
    """Pull a JSON object out of a model response, fences or not."""
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            pass
    raise LLMError("The planner did not return usable JSON.")


def _as_str_list(value: Any, limit: int, max_length: int = 280) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v).strip()[:max_length] for v in value if str(v).strip()][:limit]


async def draft_plan(
    query: str, provider: LLMProvider
) -> tuple[ResearchPlan, LLMResponse]:
    """Draft a plan for a human to approve.

    Uses the provider's constrained-output mode, so the shape is guaranteed by
    the API rather than by a regex over prose.
    """
    try:
        data, response = await provider.complete_json(
            system=PLANNER_SYSTEM,
            messages=[user_message(query)],
            schema=PLAN_SCHEMA,
            max_tokens=2000,
        )
    except NotImplementedError:  # pragma: no cover - provider without JSON mode
        response = await provider.complete(
            system=PLANNER_SYSTEM, messages=[user_message(query)], max_tokens=2000
        )
        data = _extract_json(response.text)

    # Bounds match the API contract in app/schemas.py (PlanStep max_length).
    plan = _as_str_list(data.get("plan"), limit=6, max_length=500)
    if not plan:
        # Never hand the user an empty approval screen.
        plan = [f"Research and summarise: {query.strip()[:120]}"]

    return (
        ResearchPlan(
            plan=plan,
            clarifying_questions=_as_str_list(
                data.get("clarifying_questions"), limit=3, max_length=300
            ),
            restated_question=str(data.get("restated_question", "")).strip(),
        ),
        response,
    )


# --------------------------------------------------------------------------
# Phase 2: execute the approved plan
# --------------------------------------------------------------------------
def _format_clarifications(answers: dict[str, str] | None) -> str:
    if not answers:
        return "The person did not add clarifications."
    lines = [f"Q: {q}\nA: {a}" for q, a in answers.items() if str(a).strip()]
    if not lines:
        return "The person did not add clarifications."
    return "CLARIFICATIONS FROM THE PERSON\n" + "\n".join(lines)


async def _run_search(
    call_args: dict[str, Any],
    *,
    search: SearchClient,
    budget: Budget,
    hooks: AgentHooks,
    excluded_urls: set[str],
    memo: dict[str, str],
) -> str:
    query = str(call_args.get("query", "")).strip()
    if not query:
        return "Error: `query` was empty. Provide a specific search query."

    key = " ".join(query.lower().split())
    if key in memo:
        # Models re-ask the same thing across turns; charging for it twice is
        # pure waste, so a repeat is served from the run's memo.
        return f"(Repeat of an earlier search - cached.)\n{memo[key]}"

    if budget.searches_left <= 0:
        return "Error: search budget exhausted. Write the final report now."

    # Check-then-increment with no await in between, so concurrent tool calls
    # in the same turn cannot both slip past the cap.
    budget.searches_used += 1
    await hooks.on_event("search", f"Searching: {query}", {"query": query})

    try:
        results = await search.search(query, max_results=5)
    except Exception as exc:  # surfaced to the model, not fatal to the run
        log.warning("search failed for %r: %s", query, exc)
        await hooks.on_event("error", f"Search failed: {exc}", {"query": query})
        return f"Search failed: {exc}. Try a different query or continue without it."

    kept = [r for r in results if r.url not in excluded_urls]
    for result in kept:
        await hooks.on_source(result)

    dropped = len(results) - len(kept)
    if not kept:
        return "No usable results (the person may have excluded them). Try another query."

    body = "\n".join(r.as_prompt_block() for r in kept)
    note = f"\n\n({dropped} result(s) excluded by the person.)" if dropped else ""
    remaining = budget.searches_left
    rendered = f"Results for {query!r} ({remaining} search(es) left):\n{body}{note}"
    memo[key] = rendered
    return rendered


async def run_research(
    *,
    query: str,
    plan: list[str],
    answers: dict[str, str] | None,
    provider: LLMProvider,
    search: SearchClient,
    budget: Budget,
    hooks: AgentHooks | None = None,
    excluded_urls: set[str] | None = None,
) -> ResearchOutcome:
    """Execute an approved plan and return the finished report.

    The core loop: ask the model, run whatever tools it requests, feed the results
    back, and stop when it writes the report or runs out of budget. Cancellation
    is checked between turns, and the caps are enforced here rather than trusted
    to the model.
    """
    hooks = hooks or AgentHooks()
    excluded_urls = excluded_urls or set()
    memo: dict[str, str] = {}

    system = RESEARCHER_SYSTEM.format(
        query=query.strip(),
        clarifications=_format_clarifications(answers),
        plan="\n".join(f"{i}. {step}" for i, step in enumerate(plan, start=1)),
        max_searches=budget.max_searches,
        max_iterations=budget.max_iterations,
    )
    messages: list[Message] = [
        user_message("Begin. Work through the approved plan, then write the report.")
    ]
    report = ""

    async def call_model(phase: str, **kwargs: Any) -> LLMResponse:
        """Every model call goes through here so telemetry is never forgotten."""
        response = await provider.complete(
            system=system,
            messages=messages,
            # The system prompt and tool schemas are byte-identical on every
            # turn of a run, so they carry a cache breakpoint.
            cache_prefix=True,
            **kwargs,
        )
        budget.record(response.usage)
        await hooks.on_turn(phase, response)
        return response

    while True:
        if await hooks.should_cancel():
            await hooks.on_event("status", "Cancelled by the user.")
            return ResearchOutcome(report, budget.usage, budget.searches_used, "cancelled")

        reason = budget.exhausted_reason()
        if reason:
            # Spend one last turn turning gathered evidence into a report.
            await hooks.on_event("status", f"Wrapping up early: {reason}.")
            messages.append(user_message(FINALISE_NUDGE.format(reason=reason)))
            final = await call_model("finalise", max_tokens=16_000)
            return ResearchOutcome(
                final.text or report, budget.usage, budget.searches_used, "budget"
            )

        budget.iterations_used += 1
        response = await call_model(
            "research", tools=[SEARCH_TOOL], max_tokens=16_000
        )
        messages.append(response.as_message())

        if not response.tool_calls:
            report = response.text
            if len(report) < 200:
                # Model stopped without producing a real report - ask once.
                await hooks.on_event("status", "Asking for the final write-up.")
                messages.append(
                    user_message(
                        "That is not a complete report. Write the full Markdown "
                        "report now, following the required structure."
                    )
                )
                final = await call_model("finalise", max_tokens=16_000)
                report = final.text or report
            if not report.strip():
                # Never mark a task complete with nothing in it.
                raise LLMError("The model finished without producing a report.")
            await hooks.on_event("status", "Report complete.")
            return ResearchOutcome(
                report, budget.usage, budget.searches_used, "completed"
            )

        if response.text:
            await hooks.on_event("thought", response.text[:500])

        # Models emit several searches per turn; running them concurrently
        # turns N round trips into one. Results are reassembled in call order,
        # because tool_result blocks must line up with their tool_use ids.
        async def resolve(call: ToolCall) -> Message:
            """Run one tool call and wrap the result for the model.

            A failing tool returns an error result rather than raising, so one bad search
            does not end the run.
            """
            if call.name != SEARCH_TOOL.name:
                return tool_result_message(
                    call, f"Unknown tool {call.name!r}.", is_error=True
                )
            try:
                text = await _run_search(
                    call.arguments,
                    search=search,
                    budget=budget,
                    hooks=hooks,
                    excluded_urls=excluded_urls,
                    memo=memo,
                )
            except Exception as exc:  # noqa: BLE001 - report to the model, keep going
                log.warning("tool %s failed: %s", call.name, exc)
                return tool_result_message(call, f"Tool failed: {exc}", is_error=True)
            return tool_result_message(call, text)

        results = await asyncio.gather(
            *(resolve(call) for call in response.tool_calls)
        )
        messages.extend(results)
