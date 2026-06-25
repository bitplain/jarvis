from app.core.config import Settings
from app.llm.base import LLMProvider
from app.llm.fallback import FallbackLLMProvider
from app.llm.openrouter import OpenRouterProvider
from app.llm.yandex import YandexAIStudioProvider
from app.services.runtime_settings_service import ActiveLLMProvider


def build_llm_provider(
    settings: Settings,
    *,
    active_provider: ActiveLLMProvider = ActiveLLMProvider.AUTO,
) -> LLMProvider:
    yandex = YandexAIStudioProvider(settings)
    openrouter = OpenRouterProvider(settings)
    if active_provider == ActiveLLMProvider.YANDEX:
        return yandex
    if active_provider == ActiveLLMProvider.OPENROUTER:
        return openrouter
    if settings.llm_primary_provider == "openrouter":
        return FallbackLLMProvider(primary=openrouter, fallback=yandex)
    return FallbackLLMProvider(primary=yandex, fallback=openrouter)
