"""The agent loop is the interesting code, so it gets the real tests.

Everything here runs offline against scripted providers: no API key, no network,
no spend. That is the point - the loop's guarantees (caps, cancellation, source
vetoes, parallelism) are properties of our code, not of the model.
"""
from __future__ import annotations

import pytest

from app.agent.loop import AgentHooks, Budget, draft_plan, run_research
from app.llm.base import LLMError, LLMResponse, ToolCall, Usage
from tests.fakes import CountingSearch, FakeProvider, text_turn, tool_turn

REPORT = "# Findings\n\n" + ("Substantive body text. " * 30)


async def _run(provider, search, budget, **kw):
    return await run_research(
        query="What happened to X?",
        plan=["Step one", "Step two"],
        answers={"Which year?": "2026"},
        provider=provider,
        search=search,
        budget=budget,
        **kw,
    )


# -- happy path -------------------------------------------------------------
async def test_loop_searches_then_writes_report():
    provider = FakeProvider([tool_turn("x background"), text_turn(REPORT)])
    search = CountingSearch()

    outcome = await _run(provider, search, Budget())

    assert outcome.stopped_reason == "completed"
    assert outcome.report_markdown == REPORT
    assert search.queries == ["x background"]
    assert outcome.searches_used == 1
    assert provider.calls[0]["tools"] == ["web_search"]
    # The human's clarification reached the system prompt.
    assert "2026" in provider.calls[0]["system"]


async def test_stable_prefix_is_marked_cacheable():
    """System prompt + tool schemas repeat every turn; they must be cached."""
    provider = FakeProvider([tool_turn("q"), text_turn(REPORT)])

    await _run(provider, CountingSearch(), Budget())

    assert all(call["cache_prefix"] for call in provider.calls)


async def test_every_model_call_emits_telemetry():
    provider = FakeProvider([tool_turn("q"), text_turn(REPORT)])
    turns: list[tuple[str, LLMResponse]] = []

    async def on_turn(phase, response):
        turns.append((phase, response))

    await _run(provider, CountingSearch(), Budget(), hooks=AgentHooks(on_turn=on_turn))

    assert [phase for phase, _ in turns] == ["research", "research"]
    assert all(isinstance(r, LLMResponse) for _, r in turns)


# -- spend caps -------------------------------------------------------------
async def test_search_cap_is_enforced_and_forces_a_writeup():
    provider = FakeProvider([tool_turn(f"q{i}", f"c{i}") for i in range(6)])
    search = CountingSearch()
    budget = Budget(max_searches=2, max_iterations=10)

    outcome = await _run(provider, search, budget)

    assert len(search.queries) == 2, "search cap must hold"
    assert outcome.stopped_reason == "budget"
    assert outcome.searches_used == 2


async def test_iteration_cap_is_enforced():
    provider = FakeProvider([tool_turn(f"q{i}", f"c{i}") for i in range(20)])
    budget = Budget(max_iterations=3, max_searches=50)

    outcome = await _run(provider, CountingSearch(), budget)

    assert budget.iterations_used == 3
    assert outcome.stopped_reason == "budget"


async def test_output_token_cap_is_enforced():
    first = tool_turn("q0", "c0")
    expensive = LLMResponse(first.text, first.tool_calls, "tool_use", Usage(0, 5_000))
    provider = FakeProvider(
        [expensive, *[tool_turn(f"q{i}", f"c{i}") for i in range(1, 5)]]
    )

    outcome = await _run(provider, CountingSearch(), Budget(max_output_tokens=1_000))

    assert outcome.stopped_reason == "budget"


async def test_cache_tokens_are_tracked_separately_for_costing():
    turn = text_turn(REPORT)
    priced = LLMResponse(
        turn.text, [], "end_turn", Usage(100, 200, cache_read_tokens=9_000, cache_write_tokens=500)
    )
    provider = FakeProvider([priced])

    outcome = await _run(provider, CountingSearch(), Budget())

    assert outcome.usage.cache_read_tokens == 9_000
    assert outcome.usage.cache_write_tokens == 500
    assert outcome.usage.billable_input == 9_600


# -- human control ----------------------------------------------------------
async def test_cancellation_stops_the_loop():
    provider = FakeProvider([tool_turn("q1"), text_turn(REPORT)])
    search = CountingSearch()
    cancelled = {"value": False}

    async def should_cancel():
        was = cancelled["value"]
        cancelled["value"] = True
        return was

    outcome = await _run(
        provider, search, Budget(), hooks=AgentHooks(should_cancel=should_cancel)
    )

    assert outcome.stopped_reason == "cancelled"
    assert len(search.queries) == 1


async def test_excluded_sources_are_filtered_out():
    provider = FakeProvider([tool_turn("q1"), text_turn(REPORT)])
    search = CountingSearch()

    await _run(provider, search, Budget(), excluded_urls={"https://example.com/1"})

    tool_results = [
        m for call in provider.calls for m in call["messages"] if m.role == "tool"
    ]
    assert tool_results
    assert "https://example.com/1" not in tool_results[0].content


# -- efficiency -------------------------------------------------------------
async def test_tool_calls_in_one_turn_run_concurrently():
    """Several searches per turn should be one round trip, not N."""
    turn = LLMResponse(
        text="",
        tool_calls=[
            ToolCall(id="a", name="web_search", arguments={"query": "alpha"}),
            ToolCall(id="b", name="web_search", arguments={"query": "beta"}),
            ToolCall(id="c", name="web_search", arguments={"query": "gamma"}),
        ],
        stop_reason="tool_use",
        usage=Usage(10, 5),
    )
    provider = FakeProvider([turn, text_turn(REPORT)])
    search = CountingSearch(delay=0.02)

    await _run(provider, search, Budget())

    assert search.max_concurrent == 3, "searches in a turn must overlap"
    assert sorted(search.queries) == ["alpha", "beta", "gamma"]


async def test_tool_results_are_ordered_to_match_their_calls():
    turn = LLMResponse(
        text="",
        tool_calls=[
            ToolCall(id="a", name="web_search", arguments={"query": "alpha"}),
            ToolCall(id="b", name="web_search", arguments={"query": "beta"}),
        ],
        stop_reason="tool_use",
        usage=Usage(10, 5),
    )
    provider = FakeProvider([turn, text_turn(REPORT)])

    await _run(provider, CountingSearch(delay=0.01), Budget())

    results = [m for m in provider.calls[-1]["messages"] if m.role == "tool"]
    assert [m.tool_call_id for m in results] == ["a", "b"]


async def test_repeated_query_is_served_from_the_run_memo():
    provider = FakeProvider(
        [tool_turn("same question", "c1"), tool_turn("same question", "c2"), text_turn(REPORT)]
    )
    search = CountingSearch()

    outcome = await _run(provider, search, Budget())

    assert search.queries == ["same question"], "a repeat must not hit the network"
    assert outcome.searches_used == 1, "and must not be charged to the budget"


# -- robustness -------------------------------------------------------------
async def test_unknown_tool_is_reported_without_killing_the_run():
    bad = LLMResponse(
        text="",
        tool_calls=[ToolCall(id="z", name="delete_everything", arguments={})],
        stop_reason="tool_use",
        usage=Usage(1, 1),
    )
    provider = FakeProvider([bad, text_turn(REPORT)])

    outcome = await _run(provider, CountingSearch(), Budget())

    assert outcome.stopped_reason == "completed"
    results = [m for m in provider.calls[-1]["messages"] if m.role == "tool"]
    assert results[0].is_error


async def test_search_failure_is_surfaced_to_the_model_not_fatal():
    class BrokenSearch(CountingSearch):
        async def search(self, query, *, max_results=5):
            raise RuntimeError("upstream down")

    provider = FakeProvider([tool_turn("q"), text_turn(REPORT)])

    outcome = await _run(provider, BrokenSearch(), Budget())

    assert outcome.stopped_reason == "completed"


async def test_short_answer_is_pushed_back_for_a_real_report():
    provider = FakeProvider([text_turn("Done!"), text_turn(REPORT)])

    outcome = await _run(provider, CountingSearch(), Budget())

    assert outcome.report_markdown == REPORT
    assert len(provider.calls) == 2


async def test_empty_report_is_a_failure_not_a_silent_success():
    provider = FakeProvider([text_turn(""), text_turn("")])
    with pytest.raises(LLMError):
        await _run(provider, CountingSearch(), Budget())


async def test_events_and_sources_are_reported_to_hooks():
    provider = FakeProvider([tool_turn("q1"), text_turn(REPORT)])
    events, sources = [], []

    async def on_event(kind, message, data=None):
        events.append((kind, message))

    async def on_source(result):
        sources.append(result.url)

    await _run(
        provider,
        CountingSearch(),
        Budget(),
        hooks=AgentHooks(on_event=on_event, on_source=on_source),
    )

    assert any(kind == "search" for kind, _ in events)
    assert sources == ["https://example.com/1"]


# -- planner ----------------------------------------------------------------
async def test_draft_plan_uses_constrained_output():
    provider = FakeProvider(
        [
            text_turn(
                '{"clarifying_questions": ["Which market?"], '
                '"plan": ["A", "B"], "restated_question": "R"}'
            )
        ]
    )

    plan, response = await draft_plan("q", provider)

    assert plan.plan == ["A", "B"]
    assert plan.clarifying_questions == ["Which market?"]
    assert plan.restated_question == "R"
    assert response.usage.output_tokens == 5
    # Constrained by schema rather than parsed out of prose, and no tools.
    assert provider.calls[0]["tools"] == []
    assert provider.calls[0]["schema"]["required"] == [
        "restated_question",
        "clarifying_questions",
        "plan",
    ]


async def test_draft_plan_never_returns_an_empty_plan():
    provider = FakeProvider([text_turn('{"plan": [], "clarifying_questions": []}')])
    plan, _ = await draft_plan("Some question", provider)
    assert len(plan.plan) == 1


async def test_draft_plan_truncates_oversized_steps():
    long_step = "x" * 900
    provider = FakeProvider(
        [text_turn('{"plan": ["%s"], "clarifying_questions": []}' % long_step)]
    )
    plan, _ = await draft_plan("q", provider)
    assert len(plan.plan[0]) == 500, "must match the PlanStep API contract"


async def test_draft_plan_raises_on_unparseable_output():
    provider = FakeProvider([text_turn("I'm afraid I can't do that.")])
    with pytest.raises(LLMError):
        await draft_plan("q", provider)
