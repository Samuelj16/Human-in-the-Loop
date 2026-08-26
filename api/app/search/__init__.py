"""Web search provider interface, factory registry, and stub implementations.

Exports:
  - `SearchClient`: Abstract interface for search backends.
  - `SearchResult`: Hit data structure.
  - `StubSearch`: Offline deterministic test search client.
  - `TavilySearch`: Live Tavily web search integration.
  - `get_search_client`: Search factory resolving Tavily vs Stub based on API key presence.
"""

from functools import lru_cache

from app.config import settings
from app.search.base import SearchClient, SearchResult
from app.search.stub import StubSearch
from app.search.tavily import TavilySearch


@lru_cache
def get_search_client() -> SearchClient:
    """Resolve active search client: live Tavily if API key is present, otherwise offline Stub.
    
    Returns:
        SearchClient: Configured search engine instance.
    """
    if settings.tavily_api_key:
        return TavilySearch()
    return StubSearch()


__all__ = [
    "SearchClient",
    "SearchResult",
    "StubSearch",
    "TavilySearch",
    "get_search_client",
]
