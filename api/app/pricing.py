"""Token accounting in dollars.

The approval gate is only a real decision if the person can see what they are
about to spend, so every estimate and every actual is denominated in USD rather
than tokens. Prices are per 1M tokens.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

# Anthropic list prices (USD per 1M tokens), first-party API.
# Cache multipliers are Anthropic's standard 5-minute-TTL rates:
#   writing to cache costs 1.25x input, reading from cache costs 0.10x input.
CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.10

PRICES: dict[str, tuple[float, float]] = {
    # model id: (input $/Mtok, output $/Mtok)
    "claude-fable-5": (10.00, 50.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-opus-4-7": (5.00, 25.00),
    "claude-opus-4-6": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
    # Gemini models (USD per 1M tokens)
    "gemini-3.6-flash": (0.10, 0.40),
    "gemini-2.5-flash": (0.10, 0.40),
    "gemini-2.5-pro": (1.25, 5.00),
    "gemini-1.5-flash": (0.075, 0.30),
    "gemini-1.5-pro": (1.25, 5.00),
}

# OpenAI prices are not bundled here because they are not verifiable from this
# codebase. Set OPENAI_PRICE_INPUT / OPENAI_PRICE_OUTPUT (USD per 1M tokens) to
# get real numbers for a GPT model; otherwise estimates fall back to these and
# are flagged as unverified in the API response.
FALLBACK_PRICE = (
    float(os.getenv("OPENAI_PRICE_INPUT", "2.50")),
    float(os.getenv("OPENAI_PRICE_OUTPUT", "10.00")),
)


def _configured_open_model_price(model: str) -> tuple[float, float] | None:
    """Price for an open-weight model, if this is the configured one.

    A model on your own hardware costs nothing per token, so the 0.0 default is
    not a missing value - it is the right answer, and the approval gate should
    show $0.00 rather than a guess.
    """
    from app.config import settings

    if model and model == settings.open_model_name:
        return (settings.open_model_price_input, settings.open_model_price_output)
    return None


def price_for(model: str) -> tuple[float, float]:
    if model in PRICES:
        return PRICES[model]
    configured = _configured_open_model_price(model)
    if configured is not None:
        return configured
    return FALLBACK_PRICE


def is_priced(model: str) -> bool:
    """False when we are guessing, so the UI can say so."""
    return model in PRICES or _configured_open_model_price(model) is not None


def cost_usd(
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float:
    """Dollar cost of one call (or a whole task, summed)."""
    in_price, out_price = price_for(model)
    total = (
        input_tokens * in_price
        + output_tokens * out_price
        + cache_write_tokens * in_price * CACHE_WRITE_MULTIPLIER
        + cache_read_tokens * in_price * CACHE_READ_MULTIPLIER
    )
    return round(total / 1_000_000, 6)


# --------------------------------------------------------------------------
# Pre-flight estimate, shown on the approval gate
# --------------------------------------------------------------------------
# Heuristics, deliberately explicit so they can be recalibrated against the
# `llm_turns` telemetry once real runs exist.
SYSTEM_PROMPT_TOKENS = 700       # system + plan + tool schema
SEARCH_RESULT_TOKENS = 750       # one tool result (5 snippets)
ASSISTANT_TURN_TOKENS = 350      # reasoning + tool call per research turn
REPORT_OUTPUT_TOKENS = 2_500     # the final write-up
PLANNER_INPUT_TOKENS = 400
PLANNER_OUTPUT_TOKENS = 400


@dataclass(frozen=True)
class CostEstimate:
    model: str
    expected_usd: float
    low_usd: float
    high_usd: float
    expected_searches: int
    expected_turns: int
    priced: bool

    def as_dict(self) -> dict:
        return {
            "model": self.model,
            "expected_usd": self.expected_usd,
            "low_usd": self.low_usd,
            "high_usd": self.high_usd,
            "expected_searches": self.expected_searches,
            "expected_turns": self.expected_turns,
            "priced": self.priced,
        }


def _run_cost(
    model: str, turns: int, searches: int, *, cached: bool
) -> float:
    """Cost of a run with `turns` model calls and `searches` tool results.

    Input grows every turn because the transcript is resent, so the input bill
    is a triangular number, not turns x prompt. That growth is exactly what
    prompt caching flattens, which is why `cached` matters so much here.
    """
    total = 0.0
    transcript = 0  # tokens accumulated in the conversation so far
    per_turn_growth = ASSISTANT_TURN_TOKENS + (
        SEARCH_RESULT_TOKENS if searches else 0
    )

    for turn in range(turns):
        prompt = SYSTEM_PROMPT_TOKENS + transcript
        if cached:
            # Stable prefix is read from cache; only the tail is fresh input.
            fresh = min(prompt, per_turn_growth)
            total += cost_usd(
                model,
                input_tokens=fresh,
                cache_read_tokens=max(0, prompt - fresh),
                cache_write_tokens=SYSTEM_PROMPT_TOKENS if turn == 0 else 0,
            )
        else:
            total += cost_usd(model, input_tokens=prompt)
        out = REPORT_OUTPUT_TOKENS if turn == turns - 1 else ASSISTANT_TURN_TOKENS
        total += cost_usd(model, output_tokens=out)
        transcript += per_turn_growth

    return total


def estimate_task_cost(
    plan: list[str],
    *,
    model: str,
    max_searches: int,
    max_iterations: int,
    include_planner: bool = False,
    cached: bool = True,
) -> CostEstimate:
    """What approving this plan is likely to cost.

    Expected: roughly one search per step plus a synthesis turn.
    High: the plan runs into the hard caps.
    """
    steps = max(1, len(plan))
    expected_searches = min(max_searches, steps + 1)
    expected_turns = min(max_iterations, expected_searches + 1)

    expected = _run_cost(model, expected_turns, expected_searches, cached=cached)
    high = _run_cost(model, max_iterations, max_searches, cached=cached)
    low = _run_cost(model, max(2, steps), max(1, steps), cached=cached)

    if include_planner:
        planner = cost_usd(
            model,
            input_tokens=PLANNER_INPUT_TOKENS,
            output_tokens=PLANNER_OUTPUT_TOKENS,
        )
        expected, high, low = expected + planner, high + planner, low + planner

    return CostEstimate(
        model=model,
        expected_usd=round(expected, 4),
        low_usd=round(low, 4),
        high_usd=round(max(high, expected), 4),
        expected_searches=expected_searches,
        expected_turns=expected_turns,
        priced=is_priced(model),
    )
