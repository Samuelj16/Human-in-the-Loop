"""Web search behind an interface, same reasoning as the LLM layer."""
from __future__ import annotations

import abc
from dataclasses import dataclass
from functools import lru_cache

from app.config import settings


@dataclass(frozen=True)
class SearchResult:
    """One search hit, trimmed to what the model actually needs."""
    url: str
    title: str
    snippet: str

    def as_prompt_block(self) -> str:
        """Render this hit for inclusion in a tool result."""
        return f"- {self.title}\n  {self.url}\n  {self.snippet}"


class SearchClient(abc.ABC):
    """The search surface the agent depends on - one method, so it is easy to swap."""
    name: str

    @abc.abstractmethod
    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        """Return up to `max_results` hits for `query`."""
        ...


@lru_cache
def get_search_client() -> SearchClient:
    """Tavily when a key is configured, otherwise a stub so the app still runs."""
    if settings.tavily_api_key:
        from app.search.tavily import TavilySearch

        return TavilySearch()
    from app.search.stub import StubSearch

    return StubSearch()
