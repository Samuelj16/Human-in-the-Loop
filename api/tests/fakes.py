"""Scripted testing stand-ins for LLM providers and search engines.

Provides hermetic fakes that replay deterministic turn sequences, measure concurrency,
and verify prompt cache flags without issuing network requests or incurring API costs.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from app.llm.base import LLMError, LLMProvider, LLMResponse, ToolCall, ToolSpec, Usage
from app.search.base import SearchClient, SearchResult


class FakeProvider(LLMProvider):
    """Deterministic LLMProvider fake for offline hermetic testing.
    
    Replays a scripted list of `LLMResponse` objects and records every invocation's
    arguments for assertion inspection.
    """

    name = "fake"
    model = "fake-1"

    def __init__(self, script: list[LLMResponse]) -> None:
        """Initialize FakeProvider.
        
        Args:
            script: Pre-scripted responses to yield sequentially.
        """
        self.script = list(script)
        self.calls: list[dict[str, Any]] = []

    async def complete(
        self,
        *,
        system: str,
        messages: list[Any],
        tools: list[ToolSpec] | None = None,
        max_tokens: int = 8000,
        cache_prefix: bool = False,
    ) -> LLMResponse:
        """Record the call arguments and pop the next scripted response."""
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

    async def complete_json(
        self,
        *,
        system: str,
        messages: list[Any],
        schema: dict[str, Any],
        max_tokens: int = 2000,
    ) -> tuple[dict[str, Any], LLMResponse]:
        """Mimic structured JSON completion mode."""
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
    """Helper creating a simulated LLM response containing a web search tool call."""
    return LLMResponse(
        text="",
        tool_calls=[ToolCall(id=call_id, name="web_search", arguments={"query": query})],
        stop_reason="tool_use",
        usage=Usage(10, 5),
    )


def text_turn(text: str) -> LLMResponse:
    """Helper creating a simulated final text response."""
    return LLMResponse(text=text, tool_calls=[], stop_reason="end_turn", usage=Usage(10, 5))


class CountingSearch(SearchClient):
    """SearchClient fake tracking concurrency and query history."""
    name = "counting"

    def __init__(self, delay: float = 0.0) -> None:
        """Initialize CountingSearch.
        
        Args:
            delay: Optional simulated latency in seconds.
        """
        self.queries: list[str] = []
        self.concurrent = 0
        self.max_concurrent = 0
        self._delay = delay

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        """Record query and measure concurrent search invocations."""
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

