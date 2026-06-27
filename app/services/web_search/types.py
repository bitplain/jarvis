from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str
    source: str | None = None
    published_at: datetime | None = None


class WebSearchStatus(StrEnum):
    OK = "ok"
    DISABLED = "disabled"
    CONFIG_ERROR = "config_error"
    INVALID_QUERY = "invalid_query"
    NO_RESULTS = "no_results"
    PROVIDER_ERROR = "provider_error"


@dataclass(frozen=True)
class WebSearchRequest:
    query: str
    provider_name: str
    enabled: bool
    max_results: int


@dataclass(frozen=True)
class WebSearchResponse:
    status: WebSearchStatus
    results: list[SearchResult]
    user_message: str | None = None
    from_cache: bool = False


def search_result_to_json(result: SearchResult) -> dict[str, Any]:
    return {
        "title": result.title,
        "url": result.url,
        "snippet": result.snippet,
        "source": result.source,
        "published_at": result.published_at.isoformat() if result.published_at else None,
    }


def search_result_from_json(value: dict[str, Any]) -> SearchResult:
    raw_published_at = value.get("published_at")
    published_at = None
    if isinstance(raw_published_at, str) and raw_published_at:
        try:
            published_at = datetime.fromisoformat(raw_published_at)
        except ValueError:
            published_at = None
    return SearchResult(
        title=str(value.get("title") or ""),
        url=str(value.get("url") or ""),
        snippet=str(value.get("snippet") or ""),
        source=str(value["source"]) if value.get("source") is not None else None,
        published_at=published_at,
    )
