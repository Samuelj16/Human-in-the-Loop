"""Tavily search client adapter."""
from __future__ import annotations

import httpx

from app.config import settings
from app.search.base import SearchClient, SearchResult

ENDPOINT = "https://api.tavily.com/search"


class SearchError(RuntimeError):
    """Tavily rejected the request or is unreachable."""
    pass


class TavilySearch(SearchClient):
    """Tavily search client adapter.

    Provides structured web research search results tailored for agentic workflows
    via Tavily's REST API (`https://api.tavily.com/search`).
    """
    name = "tavily"

    def __init__(self, api_key: str | None = None) -> None:
        """Initialize Tavily search client.
        
        Args:
            api_key: Optional explicit API key. Defaults to settings.tavily_api_key.
        """
        self._api_key = api_key or settings.tavily_api_key

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        """Execute a web search against Tavily.
        
        Args:
            query: The search inquiry string.
            max_results: Max hits to request (default 5).
            
        Returns:
            list[SearchResult]: Parsed search hits.
            
        Raises:
            SearchError: If configuration is missing or request fails.
        """
        if not self._api_key:
            raise SearchError("TAVILY_API_KEY is not set")

        payload = {
            "query": query,
            "max_results": max_results,
            "search_depth": "basic",
            "include_answer": False,
            "include_raw_content": False,
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                ENDPOINT,
                json=payload,
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
            if response.status_code in (401, 403, 422):
                # Older Tavily keys authenticate via a body field instead.
                response = await client.post(
                    ENDPOINT, json={**payload, "api_key": self._api_key}
                )
            if response.status_code >= 400:
                raise SearchError(
                    f"Tavily returned {response.status_code}: {response.text[:200]}"
                )
            body = response.json()

        return [
            SearchResult(
                url=item.get("url", ""),
                title=item.get("title", "") or item.get("url", ""),
                snippet=(item.get("content", "") or "")[:1200],
            )
            for item in body.get("results", [])
            if item.get("url")
        ]

