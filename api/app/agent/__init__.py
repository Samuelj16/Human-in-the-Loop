"""Public research-agent package exports.

Provides the core orchestration machinery for the human-in-the-loop agent:
  - `AgentHooks`: Callbacks for event streaming, source recording, cancellation, and telemetry.
  - `Budget`: Guardrails for token usage, maximum searches, and maximum turn iterations.
  - `ResearchPlan`: Draft plan structure awaiting human approval.
  - `ResearchOutcome`: Final report and telemetry outcome.
  - `draft_plan`: Phase 1 planner entrypoint.
  - `run_research`: Phase 2 tool loop research execution entrypoint.
"""

from app.agent.loop import (
    AgentHooks,
    Budget,
    ResearchOutcome,
    ResearchPlan,
    draft_plan,
    run_research,
)

__all__ = [
    "AgentHooks",
    "Budget",
    "ResearchOutcome",
    "ResearchPlan",
    "draft_plan",
    "run_research",
]

