from datetime import datetime
from typing import Any

import httpx

from app.services.web_search.provider import WebSearchProviderError
from app.services.web_search.types import SearchResult


class TavilySearchProvider:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.tavily.com/search",
        timeout: float = 10.0,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = timeout

    async def search(self, query: str, *, max_results: int) -> list[SearchResult]:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {
            "query": query,
            "max_results": max_results,
            "include_answer": False,
            "include_raw_content": False,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(self.base_url, headers=headers, json=payload)
            if response.status_code >= 400:
                raise WebSearchProviderError("tavily_http_error")
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise WebSearchProviderError("tavily_network_or_decode_error") from exc
        return [_tavily_result(item) for item in data.get("results", []) if isinstance(item, dict)]


def _tavily_result(item: dict[str, Any]) -> SearchResult:
    published_at = None
    raw_published_at = item.get("published_date") or item.get("published_at")
    if isinstance(raw_published_at, str):
        try:
            published_at = datetime.fromisoformat(raw_published_at)
        except ValueError:
            published_at = None
    url = str(item.get("url") or "")
    return SearchResult(
        title=str(item.get("title") or url),
        url=url,
        snippet=str(item.get("content") or item.get("snippet") or ""),
        source=str(item.get("source") or "") or None,
        published_at=published_at,
    )
