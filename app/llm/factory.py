from app.core.config import Settings
from app.llm.base import LLMProvider
from app.llm.fallback import FallbackLLMProvider
from app.llm.openrouter import OpenRouterProvider
from app.llm.yandex import YandexAIStudioProvider


def build_llm_provider(settings: Settings) -> LLMProvider:
    yandex = YandexAIStudioProvider(settings)
    openrouter = OpenRouterProvider(settings)
    if settings.llm_primary_provider == "openrouter":
        return FallbackLLMProvider(primary=openrouter, fallback=yandex)
    return FallbackLLMProvider(primary=yandex, fallback=openrouter)
