"""Web search behind an interface, same reasoning as the LLM layer."""
from __future__ import annotations

import abc
from dataclasses import dataclass
from functools import lru_cache

from app.config import settings


@dataclass(frozen=True)
class SearchResult:
    url: str
    title: str
    snippet: str

    def as_prompt_block(self) -> str:
        return f"- {self.title}\n  {self.url}\n  {self.snippet}"


class SearchClient(abc.ABC):
    name: str

    @abc.abstractmethod
    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        ...


@lru_cache
def get_search_client() -> SearchClient:
    """Tavily when a key is configured, otherwise a stub so the app still runs."""
    if settings.tavily_api_key:
        from app.search.tavily import TavilySearch

        return TavilySearch()
    from app.search.stub import StubSearch

    return StubSearch()
