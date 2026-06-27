from app.core.config import Settings
from app.db.repositories.web_search_cache import WebSearchCacheRepository
from app.services.web_search.brave import BraveSearchProvider
from app.services.web_search.provider import WebSearchProvider
from app.services.web_search.service import WebSearchService
from app.services.web_search.tavily import TavilySearchProvider


def build_web_search_provider(settings: Settings, provider_name: str) -> WebSearchProvider | None:
    normalized = provider_name.strip().lower()
    if normalized == "tavily":
        if not settings.tavily_api_key:
            return None
        return TavilySearchProvider(api_key=settings.tavily_api_key)
    if normalized == "brave":
        if not settings.brave_search_api_key:
            return None
        return BraveSearchProvider(api_key=settings.brave_search_api_key)
    return None


def build_web_search_service(
    settings: Settings,
    *,
    provider_name: str,
    cache_repository: WebSearchCacheRepository | None,
) -> WebSearchService:
    return WebSearchService(
        provider=build_web_search_provider(settings, provider_name),
        cache=cache_repository,
    )
