from datetime import datetime
from typing import Any

import httpx

from app.services.web_search.provider import WebSearchProviderError
from app.services.web_search.types import SearchResult


class BraveSearchProvider:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.search.brave.com/res/v1/web/search",
        timeout: float = 10.0,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = timeout

    async def search(self, query: str, *, max_results: int) -> list[SearchResult]:
        headers = {
            "Accept": "application/json",
            "X-Subscription-Token": self.api_key,
        }
        params: dict[str, str | int] = {"q": query, "count": max_results}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(self.base_url, headers=headers, params=params)
            if response.status_code >= 400:
                raise WebSearchProviderError("brave_http_error")
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise WebSearchProviderError("brave_network_or_decode_error") from exc
        web = data.get("web") if isinstance(data, dict) else None
        results = web.get("results", []) if isinstance(web, dict) else []
        return [_brave_result(item) for item in results if isinstance(item, dict)]


def _brave_result(item: dict[str, Any]) -> SearchResult:
    published_at = None
    raw_age = item.get("age")
    if isinstance(raw_age, str):
        try:
            published_at = datetime.fromisoformat(raw_age)
        except ValueError:
            published_at = None
    url = str(item.get("url") or "")
    return SearchResult(
        title=str(item.get("title") or url),
        url=url,
        snippet=str(item.get("description") or item.get("snippet") or ""),
        source=str(item.get("profile", {}).get("name") or "") or None
        if isinstance(item.get("profile"), dict)
        else None,
        published_at=published_at,
    )
