"""Search client abstract interface and data structures.

This module defines the search client contract consumed by the research agent loop:
  - `SearchResult`: Data model containing url, title, snippet, and prompt formatting helpers.
  - `SearchClient`: Abstract base class implemented by `TavilySearch` and `StubSearch`.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass
from functools import lru_cache

from app.config import settings


@dataclass(frozen=True)
class SearchResult:
    """One search hit."""
    url: str                # Unique destination web URL
    title: str              # Page title
    snippet: str            # Extracted textual snippet or summary from the page

    def as_prompt_block(self) -> str:
        """Render for injection into the research loop prompt."""
        return (
            f"TITLE: {self.title}\n"
            f"URL: {self.url}\n"
            f"EXTRACT: {self.snippet}\n"
        )


class SearchClient(abc.ABC):
    """Abstract interface for web search engines."""

    @abc.abstractmethod
    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """Perform a web search query.
        
        Args:
            query: Specific search terms or question.
            max_results: Maximum number of results to return.
            
        Returns:
            list[SearchResult]: Retrieved web search results.
        """
        ...


@lru_cache
def get_search_client() -> SearchClient:
    """Tavily when a key is configured, otherwise a stub so the app still runs."""
    if settings.tavily_api_key:
        from app.search.tavily import TavilySearch

        return TavilySearch()
    from app.search.stub import StubSearch

    return StubSearch()
