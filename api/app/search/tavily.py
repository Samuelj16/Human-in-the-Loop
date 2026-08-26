"""Tavily search client."""
from __future__ import annotations

import httpx

from app.config import settings
from app.search.base import SearchClient, SearchResult

ENDPOINT = "https://api.tavily.com/search"


class SearchError(RuntimeError):
    """Tavily rejected the request or is unreachable."""
    pass


class TavilySearch(SearchClient):
    """Tavily client.

    Tries bearer auth first and falls back to the older body-field key, so a key
    of either vintage works without configuration.
    """
    name = "tavily"

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or settings.tavily_api_key
        if not self._api_key:
            raise SearchError("TAVILY_API_KEY is not set")

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        """Run one search and return the hits, raising SearchError on failure."""
        payload = {
            "query": query,
            "max_results": max_results,
            "search_depth": "basic",
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
