"""Scripted stand-ins for the model and the search engine."""
from __future__ import annotations

import asyncio
import json

from app.llm.base import LLMError, LLMProvider, LLMResponse, ToolCall, Usage
from app.search.base import SearchClient, SearchResult


class FakeProvider(LLMProvider):
    """Replays a scripted list of LLMResponses, recording what it was sent."""

    name = "fake"
    model = "fake-1"

    def __init__(self, script: list[LLMResponse]) -> None:
        self.script = list(script)
        self.calls: list[dict] = []

    async def complete(
        self, *, system, messages, tools=None, max_tokens=8000, cache_prefix=False
    ):
        self.calls.append(
            {
                "system": system,
                "messages": list(messages),
                "tools": [t.name for t in (tools or [])],
                "max_tokens": max_tokens,
                "cache_prefix": cache_prefix,
            }
        )
        if not self.script:
            return LLMResponse("Fallback report body. " * 20, [], "end_turn", Usage(1, 1))
        return self.script.pop(0)

    async def complete_json(self, *, system, messages, schema, max_tokens=2000):
        """Mimics constrained output: the scripted text must be valid JSON."""
        self.calls.append(
            {
                "system": system,
                "messages": list(messages),
                "tools": [],
                "schema": schema,
                "max_tokens": max_tokens,
            }
        )
        response = (
            self.script.pop(0)
            if self.script
            else LLMResponse("{}", [], "end_turn", Usage(1, 1))
        )
        try:
            return json.loads(response.text), response
        except json.JSONDecodeError as exc:
            raise LLMError(f"not valid JSON: {response.text[:80]}") from exc


def tool_turn(query: str, call_id: str = "c1") -> LLMResponse:
    return LLMResponse(
        text="",
        tool_calls=[ToolCall(id=call_id, name="web_search", arguments={"query": query})],
        stop_reason="tool_use",
        usage=Usage(10, 5),
    )


def text_turn(text: str) -> LLMResponse:
    return LLMResponse(text=text, tool_calls=[], stop_reason="end_turn", usage=Usage(10, 5))


class CountingSearch(SearchClient):
    name = "counting"

    def __init__(self, delay: float = 0.0) -> None:
        self.queries: list[str] = []
        self.concurrent = 0
        self.max_concurrent = 0
        self._delay = delay

    async def search(self, query: str, *, max_results: int = 5):
        self.concurrent += 1
        self.max_concurrent = max(self.max_concurrent, self.concurrent)
        if self._delay:
            await asyncio.sleep(self._delay)
        self.concurrent -= 1
        self.queries.append(query)
        return [
            SearchResult(
                url=f"https://example.com/{len(self.queries)}",
                title=f"Result for {query}",
                snippet="Evidence.",
            )
        ]
