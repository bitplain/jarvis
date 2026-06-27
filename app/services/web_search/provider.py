from typing import Protocol

from app.services.web_search.types import SearchResult


class WebSearchProvider(Protocol):
    async def search(self, query: str, *, max_results: int) -> list[SearchResult]:
        ...


class WebSearchProviderError(Exception):
    pass
