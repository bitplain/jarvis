import html

from app.services.web_search.types import SearchResult

DEFAULT_MAX_CONTEXT_CHARS = 6000
MAX_SNIPPET_CHARS = 900


def _clean_text(value: str, *, max_chars: int | None = None) -> str:
    clean = " ".join(str(value).split())
    if max_chars is not None and len(clean) > max_chars:
        clean = clean[: max_chars - 1].rstrip() + "…"
    return html.escape(clean, quote=False)


def build_search_context(
    results: list[SearchResult],
    *,
    max_total_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
) -> str:
    lines = ["Найденные источники:"]
    for index, result in enumerate(results, start=1):
        block = [
            "",
            f"[{index}] {_clean_text(result.title)}",
            f"URL: {result.url}",
            f"Snippet: {_clean_text(result.snippet, max_chars=MAX_SNIPPET_CHARS)}",
        ]
        if result.source:
            block.append(f"Source: {_clean_text(result.source)}")
        if result.published_at:
            block.append(f"Published: {result.published_at.isoformat()}")
        candidate = "\n".join(lines + block)
        if len(candidate) > max_total_chars:
            break
        lines.extend(block)
    context = "\n".join(lines)
    return context[:max_total_chars]


def build_sources_text(results: list[SearchResult]) -> str:
    lines = ["Источники:"]
    for index, result in enumerate(results, start=1):
        lines.append(f"{index}. {_clean_text(result.title)} — {result.url}")
    return "\n".join(lines)


def build_search_system_prompt(base_prompt: str, search_context: str) -> str:
    instruction = (
        "Ответь на русском. Используй только найденные источники для актуальных фактов. "
        "Если источники недостаточны, скажи об этом. В конце дай список источников."
    )
    return f"{base_prompt}\n\n{instruction}\n\n{search_context}"
