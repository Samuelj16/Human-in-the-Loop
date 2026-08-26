"""Deterministic stand-in for Tavily.

Keeps the whole flow demoable (and tests hermetic) with no search key set.
Results are clearly labelled so nobody mistakes them for real sources.
"""
from __future__ import annotations

from app.search.base import SearchClient, SearchResult


class StubSearch(SearchClient):
    """Offline stand-in for Tavily.

    Results are labelled [STUB RESULT] so nobody mistakes them for real sources.
    """
    name = "stub"

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        """Return deterministic placeholder hits for `query`."""
        return [
            SearchResult(
                url=f"https://example.com/stub/{i}?q={query.replace(' ', '+')}",
                title=f"[STUB RESULT {i}] {query}",
                snippet=(
                    "Placeholder search result. Set TAVILY_API_KEY to search the "
                    f"real web. Query was: {query!r}."
                ),
            )
            for i in range(1, min(max_results, 3) + 1)
        ]
