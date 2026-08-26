"""Offline search stub for tests and evaluation without API keys.

Generates deterministic mock search hits so tests, demos, and evaluation suites
can run completely offline with no network dependencies and zero spend.
"""
from __future__ import annotations

import hashlib
import re

from app.search.base import SearchClient, SearchResult


class StubSearch(SearchClient):
    """Generates fake, deterministic search hits so tests run offline."""
    name = "stub"

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """Generate deterministic stub results based on the search query.
        
        Args:
            query: The search query.
            max_results: Maximum results to generate (default 5).
            
        Returns:
            list[SearchResult]: Synthetic search results.
        """
        # Generate stable slug from query text
        slug = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")[:40] or "query"
        h = hashlib.sha256(query.encode("utf-8")).hexdigest()[:8]

        return [
            SearchResult(
                url=f"https://example.com/research/{slug}-{i}-{h}",
                title=f"Source {i}: {query.strip().title()}",
                snippet=(
                    f"Relevant finding {i} regarding '{query.strip()}': "
                    f"Synthetic analysis indicates key trends and metrics ({h[:4]}-{i})."
                ),
            )
            for i in range(1, max_results + 1)
        ]
