import html
import re

from app.services.web_search.types import SearchResult
from app.services.web_search.url_safety import is_safe_public_http_url

DEFAULT_MAX_CONTEXT_CHARS = 6000
MAX_SNIPPET_CHARS = 900
MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
MARKDOWN_MARKERS_RE = re.compile(r"(\*\*|__|\*|_)")


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


def format_web_search_answer_html(answer: str, results: list[SearchResult]) -> str:
    clean_answer = _markdown_to_safe_html(answer.strip())
    lines = ["<b>Нашёл актуальные источники.</b>", ""]
    if clean_answer:
        lines.extend([clean_answer, ""])
    lines.append("<b>Источники:</b>")
    for index, result in enumerate(results, start=1):
        title = _clean_text(result.title) or "Источник"
        url = result.url.strip()
        if is_safe_public_http_url(url):
            safe_url = html.escape(url, quote=True)
            lines.append(f'{index}. <a href="{safe_url}">{title}</a>')
        else:
            lines.append(f"{index}. {title}")
    return "\n".join(lines)


def build_search_system_prompt(base_prompt: str, search_context: str) -> str:
    instruction = (
        "Ответь на русском. Используй только найденные источники для актуальных фактов. "
        "Если источники недостаточны, скажи об этом. В конце дай список источников."
    )
    return f"{base_prompt}\n\n{instruction}\n\n{search_context}"


def _markdown_to_safe_html(text: str) -> str:
    placeholders: dict[str, str] = {}

    def replace_link(match: re.Match[str]) -> str:
        title = MARKDOWN_MARKERS_RE.sub("", match.group(1)).strip()
        url = match.group(2).strip()
        token = f"__JARVIS_LINK_{len(placeholders)}__"
        if is_safe_public_http_url(url):
            placeholders[token] = (
                f'<a href="{html.escape(url, quote=True)}">'
                f"{html.escape(title or url, quote=False)}</a>"
            )
        else:
            placeholders[token] = html.escape(title, quote=False)
        return token

    without_links = MARKDOWN_LINK_RE.sub(replace_link, text)
    without_markers = MARKDOWN_MARKERS_RE.sub("", without_links)
    safe = html.escape(without_markers, quote=False)
    for token, value in placeholders.items():
        safe = safe.replace(token, value)
    return safe
