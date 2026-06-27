from datetime import timedelta
from typing import Any

import pytest

from app.db.models import utcnow
from app.services.web_search.service import (
    WEB_SEARCH_DISABLED_MESSAGE,
    WEB_SEARCH_KEY_MISSING_MESSAGE,
    WEB_SEARCH_SECRET_QUERY_MESSAGE,
    WebSearchService,
)
from app.services.web_search.types import SearchResult, WebSearchRequest, WebSearchStatus


class FakeProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    async def search(self, query: str, *, max_results: int) -> list[SearchResult]:
        self.calls.append((query, max_results))
        return [
            SearchResult("One", "https://example.com/one", "first"),
            SearchResult("Two", "https://example.com/two", "second"),
        ][:max_results]


class FakeCache:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], tuple[list[dict[str, Any]], Any]] = {}
        self.saved: list[dict[str, Any]] = []

    async def get_fresh(
        self,
        *,
        provider: str,
        query_hash: str,
        now: Any,
    ) -> list[dict[str, Any]] | None:
        row = self.rows.get((provider, query_hash))
        if row is None:
            return None
        results, expires_at = row
        if expires_at <= now:
            return None
        return results

    async def upsert(
        self,
        *,
        provider: str,
        query_hash: str,
        query_text: str,
        results_json: list[dict[str, Any]],
        expires_at: Any,
    ) -> None:
        self.saved.append(
            {
                "provider": provider,
                "query_hash": query_hash,
                "query_text": query_text,
                "results_json": results_json,
                "expires_at": expires_at,
            }
        )
        self.rows[(provider, query_hash)] = (results_json, expires_at)


@pytest.mark.asyncio
async def test_disabled_provider_returns_user_message_without_provider_call() -> None:
    provider = FakeProvider()
    service = WebSearchService(provider=provider, cache=None)

    result = await service.search(
        WebSearchRequest(query="Railway", provider_name="disabled", enabled=False, max_results=5)
    )

    assert result.status is WebSearchStatus.DISABLED
    assert result.user_message == WEB_SEARCH_DISABLED_MESSAGE
    assert provider.calls == []


@pytest.mark.asyncio
async def test_enabled_missing_key_returns_config_error() -> None:
    service = WebSearchService(provider=None, cache=None)

    result = await service.search(
        WebSearchRequest(query="Railway", provider_name="tavily", enabled=True, max_results=5)
    )

    assert result.status is WebSearchStatus.CONFIG_ERROR
    assert result.user_message == WEB_SEARCH_KEY_MISSING_MESSAGE


@pytest.mark.asyncio
async def test_fake_provider_returns_safe_limited_results() -> None:
    provider = FakeProvider()
    service = WebSearchService(provider=provider, cache=None)

    result = await service.search(
        WebSearchRequest(query="Railway", provider_name="fake", enabled=True, max_results=1)
    )

    assert result.status is WebSearchStatus.OK
    assert [item.title for item in result.results] == ["One"]
    assert provider.calls == [("Railway", 1)]


@pytest.mark.asyncio
async def test_cache_hit_avoids_provider_call() -> None:
    provider = FakeProvider()
    cache = FakeCache()
    now = utcnow()
    service = WebSearchService(provider=provider, cache=cache, now=lambda: now)
    query_hash = service.query_hash("Railway")
    cache.rows[("fake", query_hash)] = (
        [{"title": "Cached", "url": "https://example.com/cached", "snippet": "hit"}],
        now + timedelta(hours=1),
    )

    result = await service.search(
        WebSearchRequest(query="Railway", provider_name="fake", enabled=True, max_results=5)
    )

    assert result.status is WebSearchStatus.OK
    assert [item.title for item in result.results] == ["Cached"]
    assert provider.calls == []


@pytest.mark.asyncio
async def test_cache_expiry_calls_provider_again() -> None:
    provider = FakeProvider()
    cache = FakeCache()
    now = utcnow()
    service = WebSearchService(provider=provider, cache=cache, now=lambda: now)
    query_hash = service.query_hash("Railway")
    cache.rows[("fake", query_hash)] = (
        [{"title": "Old", "url": "https://example.com/old", "snippet": "expired"}],
        now - timedelta(minutes=1),
    )

    result = await service.search(
        WebSearchRequest(query="Railway", provider_name="fake", enabled=True, max_results=5)
    )

    assert result.status is WebSearchStatus.OK
    assert [item.title for item in result.results] == ["One", "Two"]
    assert provider.calls == [("Railway", 5)]


@pytest.mark.asyncio
async def test_cache_hit_with_only_unsafe_results_returns_no_results() -> None:
    provider = FakeProvider()
    cache = FakeCache()
    now = utcnow()
    service = WebSearchService(provider=provider, cache=cache, now=lambda: now)
    query_hash = service.query_hash("Railway")
    cache.rows[("fake", query_hash)] = (
        [{"title": "Local", "url": "http://127.0.0.1/admin", "snippet": "unsafe"}],
        now + timedelta(hours=1),
    )

    result = await service.search(
        WebSearchRequest(query="Railway", provider_name="fake", enabled=True, max_results=5)
    )

    assert result.status is WebSearchStatus.NO_RESULTS
    assert provider.calls == []


@pytest.mark.asyncio
async def test_query_length_enforced() -> None:
    provider = FakeProvider()
    service = WebSearchService(provider=provider, cache=None)

    result = await service.search(
        WebSearchRequest(query="x" * 301, provider_name="fake", enabled=True, max_results=5)
    )

    assert result.status is WebSearchStatus.INVALID_QUERY
    assert provider.calls == []


@pytest.mark.asyncio
async def test_secret_looking_query_is_not_sent_to_provider_or_cache() -> None:
    provider = FakeProvider()
    cache = FakeCache()
    service = WebSearchService(provider=provider, cache=cache)

    result = await service.search(
        WebSearchRequest(
            query="найди Authorization Bearer secret-token",
            provider_name="fake",
            enabled=True,
            max_results=5,
        )
    )

    assert result.status is WebSearchStatus.INVALID_QUERY
    assert result.user_message == WEB_SEARCH_SECRET_QUERY_MESSAGE
    assert provider.calls == []
    assert cache.saved == []
