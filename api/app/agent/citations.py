"""Check a finished report's citations against what was actually retrieved.

The agent keeps a ledger of every URL a search really returned (the `sources`
table). A report is only trustworthy to the extent its citations appear in that
ledger. Anything cited but never retrieved is, by definition, a URL the model
produced from memory - exactly the failure this project exists to make visible.

This is a mechanism, not a prompt instruction, which is why it can be trusted.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit

# Markdown links, angle-bracket links, and bare URLs.
_URL_RE = re.compile(r"https?://[^\s\)\]\>\"'`,]+", re.IGNORECASE)
_TRACKING_PARAMS = ("utm_", "fbclid", "gclid", "mc_cid", "mc_eid", "ref_src")


def normalize_url(url: str) -> str:
    """Fold away differences that do not change what page was read."""
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
    """Every URL the report points at, in order, de-duplicated."""
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
    cited: list[str] = field(default_factory=list)
    verified: list[str] = field(default_factory=list)
    unverified: list[str] = field(default_factory=list)
    unused: list[str] = field(default_factory=list)

    @property
    def verified_ratio(self) -> float:
        return round(len(self.verified) / len(self.cited), 3) if self.cited else 1.0

    @property
    def is_clean(self) -> bool:
        return not self.unverified

    def as_dict(self) -> dict:
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
    """Diff the report's URLs against the retrieval ledger."""
    ledger = {normalize_url(u) for u in retrieved_urls if u}
    cited = extract_urls(report_markdown)

    verified = [u for u in cited if u in ledger]
    unverified = [u for u in cited if u not in ledger]
    cited_set = set(cited)
    unused = sorted(u for u in ledger if u not in cited_set)

    return CitationAudit(
        cited=cited, verified=verified, unverified=unverified, unused=unused
    )
