"""Citation verification is a correctness claim, so it gets real tests."""
from app.agent.citations import audit_citations, extract_urls, normalize_url

LEDGER = [
    "https://www.example.com/report/",
    "https://data.gov/stats?year=2026",
]


def test_normalize_folds_irrelevant_differences():
    assert normalize_url("https://WWW.Example.com/a/") == normalize_url(
        "https://example.com/a"
    )
    assert normalize_url("https://x.com/p?utm_source=news&id=3") == "https://x.com/p?id=3"
    assert normalize_url("https://x.com/p#section") == "https://x.com/p"


def test_extract_urls_handles_markdown_and_bare_links():
    md = "See [the report](https://www.example.com/report/) and https://data.gov/stats?year=2026."
    assert extract_urls(md) == [
        "https://example.com/report",
        "https://data.gov/stats?year=2026",
    ]


def test_clean_report_passes():
    md = "Findings [1](https://www.example.com/report/) and [2](https://data.gov/stats?year=2026)"
    audit = audit_citations(md, LEDGER)
    assert audit.is_clean
    assert audit.verified_ratio == 1.0
    assert not audit.unverified


def test_invented_url_is_caught():
    md = "As shown in https://example.com/report and https://totally-made-up.org/paper"
    audit = audit_citations(md, LEDGER)
    assert not audit.is_clean
    assert audit.unverified == ["https://totally-made-up.org/paper"]
    assert audit.verified == ["https://example.com/report"]
    assert audit.verified_ratio == 0.5


def test_retrieved_but_uncited_sources_are_reported():
    md = "Only cites https://example.com/report"
    audit = audit_citations(md, LEDGER)
    assert audit.unused == ["https://data.gov/stats?year=2026"]


def test_report_with_no_urls_is_vacuously_clean_but_visible():
    audit = audit_citations("No links at all.", LEDGER)
    assert audit.cited == []
    assert audit.is_clean
    assert audit.unused == sorted(normalize_url(u) for u in LEDGER)
