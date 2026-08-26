"""Citation verification and ledger auditing engine.

The agent keeps a ledger of every URL a search really returned (the `sources`
table). A report is only trustworthy to the extent its citations appear in that
ledger. Anything cited but never retrieved is, by definition, a URL the model
produced from memory - exactly the failure this project exists to make visible.

Key Algorithms:
  - `normalize_url`: Strips trailing punctuation, www prefixes, default ports (80/443),
    and common tracking query parameters (`utm_*`, `fbclid`, `gclid`).
  - `extract_urls`: Regex-based extraction of Markdown links and plain HTTP/HTTPS URLs.
  - `audit_citations`: Partitions cited links into verified (in ledger) vs unverified (hallucinated),
    and identifies retrieved sources that went unused in the text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit

# Regex for Markdown links, angle-bracket links, and bare URLs.
_URL_RE = re.compile(r"https?://[^\s\)\]\>\"'`,]+", re.IGNORECASE)
# Query parameters removed during canonicalization to ensure robust URL equality
_TRACKING_PARAMS = ("utm_", "fbclid", "gclid", "mc_cid", "mc_eid", "ref_src")


def normalize_url(url: str) -> str:
    """Fold away URL differences that do not change what page was read.
    
    Performs canonicalization:
      - Trims trailing sentence punctuation.
      - Lowercases hostname and scheme.
      - Removes leading 'www.' prefix.
      - Strips standard default ports (80 for http, 443 for https).
      - Drops common marketing/tracking query parameters (utm_*, gclid, etc.).
      
    Args:
        url: Raw URL string.
        
    Returns:
        str: Normalized, canonical URL.
    """
    url = url.strip().rstrip(".,;:!?")
    try:
        parts = urlsplit(url)
    except ValueError:
        return url.lower()

    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if parts.port and parts.port not in (80, 443):
        host = f"{host}:{parts.port}"

    path = parts.path.rstrip("/") or "/"

    query = "&".join(
        piece
        for piece in parts.query.split("&")
        if piece and not piece.lower().startswith(_TRACKING_PARAMS)
    )

    return urlunsplit((parts.scheme.lower(), host, path, query, ""))


def extract_urls(markdown: str) -> list[str]:
    """Extract every unique URL referenced in the report Markdown, preserving appearance order.
    
    Args:
        markdown: The full report Markdown text.
        
    Returns:
        list[str]: Ordered list of distinct normalized URLs.
    """
    seen: set[str] = set()
    ordered: list[str] = []
    for raw in _URL_RE.findall(markdown or ""):
        norm = normalize_url(raw)
        if norm not in seen:
            seen.add(norm)
            ordered.append(norm)
    return ordered


@dataclass
class CitationAudit:
    """Audit report comparing cited URLs against the genuine retrieval ledger."""
    cited: list[str] = field(default_factory=list)        # All URLs found in the report text
    verified: list[str] = field(default_factory=list)     # URLs in report that were genuinely retrieved
    unverified: list[str] = field(default_factory=list)   # URLs in report NEVER retrieved (hallucinations)
    unused: list[str] = field(default_factory=list)       # URLs retrieved during search but not cited

    @property
    def verified_ratio(self) -> float:
        """Fraction of cited URLs that were genuinely retrieved (0.0 to 1.0)."""
        return round(len(self.verified) / len(self.cited), 3) if self.cited else 1.0

    @property
    def is_clean(self) -> bool:
        """True when the report cites nothing the agent did not actually fetch."""
        return not self.unverified

    def as_dict(self) -> dict:
        """JSON-serialisable form, stored on the task and rendered by the UI."""
        return {
            "cited_count": len(self.cited),
            "verified_count": len(self.verified),
            "unverified_count": len(self.unverified),
            "unused_count": len(self.unused),
            "verified_ratio": self.verified_ratio,
            "is_clean": self.is_clean,
            "verified": self.verified,
            "unverified": self.unverified,
            "unused": self.unused,
        }


def audit_citations(report_markdown: str, retrieved_urls: list[str]) -> CitationAudit:
    """Diff the report's URLs against the retrieval ledger.
    
    Args:
        report_markdown: Synthesized Markdown text of the report.
        retrieved_urls: List of URLs genuinely returned by searches and stored in DB.
        
    Returns:
        CitationAudit: The audit breakdown.
    """
    ledger = {normalize_url(u) for u in retrieved_urls if u}
    cited = extract_urls(report_markdown)

    verified = [u for u in cited if u in ledger]
    unverified = [u for u in cited if u not in ledger]
    cited_set = set(cited)
    unused = sorted(u for u in ledger if u not in cited_set)

    return CitationAudit(
        cited=cited, verified=verified, unverified=unverified, unused=unused
    )

