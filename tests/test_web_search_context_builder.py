from datetime import UTC, datetime

from app.services.web_search.context_builder import (
    build_search_context,
    build_sources_text,
    format_web_search_answer_html,
)
from app.services.web_search.types import SearchResult


def test_build_search_context_escapes_text_and_keeps_urls() -> None:
    result = SearchResult(
        title="<Railway> & updates",
        url="https://example.com/railway",
        snippet="<b>Latest</b> release & pricing",
        source="example.com",
        published_at=datetime(2026, 6, 27, 12, 0, tzinfo=UTC),
    )

    context = build_search_context([result], max_total_chars=1000)

    assert "&lt;Railway&gt; &amp; updates" in context
    assert "&lt;b&gt;Latest&lt;/b&gt; release &amp; pricing" in context
    assert "https://example.com/railway" in context
    assert "<b>Latest</b>" not in context


def test_build_search_context_truncates_long_snippets_and_total_chars() -> None:
    results = [
        SearchResult(
            title=f"Title {index}",
            url=f"https://example.com/{index}",
            snippet="x" * 2000,
        )
        for index in range(5)
    ]

    context = build_search_context(results, max_total_chars=1200)

    assert len(context) <= 1200
    assert "Title 0" in context
    assert "x" * 2000 not in context


def test_build_sources_text_is_deterministic() -> None:
    sources = build_sources_text(
        [
            SearchResult("First", "https://example.com/1", "one"),
            SearchResult("Second", "https://example.com/2", "two"),
        ]
    )

    assert sources == (
        "Источники:\n"
        "1. First — https://example.com/1\n"
        "2. Second — https://example.com/2"
    )


def test_format_web_search_answer_html_strips_markdown_and_escapes_provider_text() -> None:
    html = format_web_search_answer_html(
        "**Сейчас:**\n**+17°C**\n<script>alert(1)</script>\n[bad](javascript:alert(1))",
        [
            SearchResult(
                "<Weather>",
                "https://example.com/weather",
                "<script>unsafe</script>",
            )
        ],
    )

    assert "**" not in html
    assert "<script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "&lt;Weather&gt;" in html
    assert '<a href="https://example.com/weather">' in html
    assert "javascript:alert" not in html
