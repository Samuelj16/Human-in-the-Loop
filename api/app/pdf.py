"""Markdown report -> PDF.

WeasyPrint rather than ReportLab (the report is already Markdown, so laying it
out by hand is wasted work) and rather than Puppeteer (no headless Chrome to
ship in the API container). WeasyPrint needs Pango/Cairo present, so the import
is deferred and its absence degrades to a clear 503 instead of a boot failure.
"""
from __future__ import annotations

from functools import lru_cache

STYLESHEET = """
@page { size: A4; margin: 20mm 18mm; @bottom-center { content: counter(page); font-size: 9pt; color: #666; } }
body { font-family: -apple-system, "Helvetica Neue", Arial, sans-serif; font-size: 10.5pt; line-height: 1.55; color: #1a1a1a; }
h1 { font-size: 20pt; margin: 0 0 4pt; line-height: 1.2; }
h2 { font-size: 13pt; margin: 18pt 0 6pt; border-bottom: 1px solid #e2e2e2; padding-bottom: 3pt; }
h3 { font-size: 11pt; margin: 12pt 0 4pt; }
.meta { color: #666; font-size: 9pt; margin-bottom: 16pt; }
a { color: #1a4fd6; word-break: break-word; }
code { background: #f4f4f5; padding: 1pt 3pt; border-radius: 2pt; font-size: 9pt; }
blockquote { margin: 8pt 0; padding-left: 10pt; border-left: 3px solid #ddd; color: #444; }
li { margin-bottom: 3pt; }
table { border-collapse: collapse; width: 100%; font-size: 9.5pt; }
th, td { border: 1px solid #ddd; padding: 4pt 6pt; text-align: left; }
"""


class PDFUnavailable(RuntimeError):
    """WeasyPrint (or its system libraries) is not installed in this image."""


@lru_cache
def _weasyprint():
    try:
        import weasyprint  # noqa: PLC0415
    except (ImportError, OSError) as exc:  # OSError = missing Pango/Cairo
        raise PDFUnavailable(
            "PDF export needs WeasyPrint and its Pango/Cairo system libraries "
            "(`brew install pango` locally; already present in the API image)."
        ) from exc
    return weasyprint


def markdown_to_html(md_text: str) -> str:
    """Render report Markdown to HTML for the PDF pass."""
    import markdown  # noqa: PLC0415

    return markdown.markdown(
        md_text, extensions=["extra", "sane_lists", "toc", "nl2br"]
    )


def render_report_pdf(query: str, report_markdown: str) -> bytes:
    """Render a finished report to PDF bytes.

    Raises PDFUnavailable rather than crashing the process when the system
    libraries are missing, so PDF export degrades to a 503.
    """
    weasyprint = _weasyprint()
    html = f"""<!doctype html><html><head><meta charset="utf-8">
<style>{STYLESHEET}</style></head><body>
<div class="meta">Human in the Loop &middot; research report<br>Question: {_escape(query)}</div>
{markdown_to_html(report_markdown)}
</body></html>"""
    return weasyprint.HTML(string=html).write_pdf()


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
