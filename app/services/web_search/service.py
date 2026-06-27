import hashlib
import logging
import re
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, Protocol

from app.db.models import utcnow
from app.services.web_search.provider import WebSearchProvider, WebSearchProviderError
from app.services.web_search.types import (
    SearchResult,
    WebSearchRequest,
    WebSearchResponse,
    WebSearchStatus,
    search_result_from_json,
    search_result_to_json,
)
from app.services.web_search.url_safety import is_safe_public_http_url

WEB_SEARCH_DISABLED_MESSAGE = (
    "Интернет-поиск выключен. Включите его в /settings -> Интернет-поиск."
)
WEB_SEARCH_KEY_MISSING_MESSAGE = "Интернет-поиск включён, но ключ provider не настроен."
WEB_SEARCH_NO_RESULTS_MESSAGE = "Ничего надёжного не нашёл по запросу."
WEB_SEARCH_INVALID_QUERY_MESSAGE = "Запрос для интернет-поиска слишком длинный."
WEB_SEARCH_SECRET_QUERY_MESSAGE = "Похоже на секрет. Я не буду искать это в интернете."
WEB_SEARCH_PROVIDER_ERROR_MESSAGE = "Интернет-поиск временно недоступен. Попробуйте позже."
MAX_QUERY_LENGTH = 300
MAX_RESULTS_LIMIT = 10
DEFAULT_CACHE_TTL = timedelta(hours=1)
NEWS_CACHE_TTL = timedelta(minutes=30)
SECRET_QUERY_PATTERNS = (
    re.compile(r"\b(api[_\s-]?key|authorization|bearer|password|passwd|token|secret)\b", re.I),
    re.compile(r"\b[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b", re.I),
)
logger = logging.getLogger(__name__)


class WebSearchCacheProtocol(Protocol):
    async def get_fresh(
        self,
        *,
        provider: str,
        query_hash: str,
        now: datetime,
    ) -> list[dict[str, Any]] | None:
        ...

    async def upsert(
        self,
        *,
        provider: str,
        query_hash: str,
        query_text: str,
        results_json: list[dict[str, Any]],
        expires_at: datetime,
    ) -> None:
        ...


class WebSearchService:
    def __init__(
        self,
        *,
        provider: WebSearchProvider | None,
        cache: WebSearchCacheProtocol | None,
        now: Callable[[], datetime] = utcnow,
    ) -> None:
        self.provider = provider
        self.cache = cache
        self.now = now

    async def search(self, request: WebSearchRequest) -> WebSearchResponse:
        query = " ".join(request.query.split())
        max_results = max(1, min(int(request.max_results), MAX_RESULTS_LIMIT))
        provider_name = request.provider_name.strip().lower() or "disabled"
        if not request.enabled or provider_name == "disabled":
            return WebSearchResponse(
                WebSearchStatus.DISABLED,
                [],
                WEB_SEARCH_DISABLED_MESSAGE,
            )
        if len(query) > MAX_QUERY_LENGTH:
            return WebSearchResponse(
                WebSearchStatus.INVALID_QUERY,
                [],
                WEB_SEARCH_INVALID_QUERY_MESSAGE,
            )
        if _looks_like_secret_query(query):
            return WebSearchResponse(
                WebSearchStatus.INVALID_QUERY,
                [],
                WEB_SEARCH_SECRET_QUERY_MESSAGE,
            )
        if self.provider is None:
            return WebSearchResponse(
                WebSearchStatus.CONFIG_ERROR,
                [],
                WEB_SEARCH_KEY_MISSING_MESSAGE,
            )
        now = self.now()
        query_hash = self.query_hash(query)
        if self.cache is not None:
            cached = await self.cache.get_fresh(
                provider=provider_name,
                query_hash=query_hash,
                now=now,
            )
            if cached is not None:
                cached_results = self._filter_safe_results(
                    [search_result_from_json(item) for item in cached],
                    max_results=max_results,
                )
                if not cached_results:
                    return WebSearchResponse(
                        WebSearchStatus.NO_RESULTS,
                        [],
                        WEB_SEARCH_NO_RESULTS_MESSAGE,
                    )
                return WebSearchResponse(
                    WebSearchStatus.OK,
                    cached_results,
                    from_cache=True,
                )
        try:
            raw_results = await self.provider.search(query, max_results=max_results)
        except WebSearchProviderError as exc:
            logger.warning(
                "web_search_provider_failed",
                extra={"provider": provider_name, "error_type": type(exc).__name__},
            )
            return WebSearchResponse(
                WebSearchStatus.PROVIDER_ERROR,
                [],
                WEB_SEARCH_PROVIDER_ERROR_MESSAGE,
            )
        results = self._filter_safe_results(raw_results, max_results=max_results)
        if not results:
            return WebSearchResponse(WebSearchStatus.NO_RESULTS, [], WEB_SEARCH_NO_RESULTS_MESSAGE)
        if self.cache is not None:
            await self.cache.upsert(
                provider=provider_name,
                query_hash=query_hash,
                query_text=query,
                results_json=[search_result_to_json(item) for item in results],
                expires_at=now + self._ttl_for_query(query),
            )
        return WebSearchResponse(WebSearchStatus.OK, results)

    def query_hash(self, query: str) -> str:
        return hashlib.sha256(" ".join(query.split()).casefold().encode()).hexdigest()

    def _filter_safe_results(
        self,
        results: list[SearchResult],
        *,
        max_results: int,
    ) -> list[SearchResult]:
        safe: list[SearchResult] = []
        for result in results:
            if not result.title.strip() or not result.url.strip():
                continue
            if not is_safe_public_http_url(result.url):
                continue
            safe.append(result)
            if len(safe) >= max_results:
                break
        return safe

    def _ttl_for_query(self, query: str) -> timedelta:
        lowered = query.casefold()
        if any(marker in lowered for marker in ("последние", "сегодня", "новости", "что нового")):
            return NEWS_CACHE_TTL
        return DEFAULT_CACHE_TTL


def _looks_like_secret_query(query: str) -> bool:
    return any(pattern.search(query) is not None for pattern in SECRET_QUERY_PATTERNS)
