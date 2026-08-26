"""Search abstractions and configured search-client selection."""

from app.search.base import SearchClient, SearchResult, get_search_client

__all__ = ["SearchClient", "SearchResult", "get_search_client"]
