from app.core.config import Settings
from app.llm.factory import build_llm_provider
from app.llm.fallback import FallbackLLMProvider
from app.llm.openrouter import OpenRouterProvider
from app.llm.yandex import YandexAIStudioProvider
from app.services.runtime_settings_service import ActiveLLMProvider


def test_auto_provider_uses_existing_env_primary_fallback_path() -> None:
    provider = build_llm_provider(
        Settings(llm_primary_provider="openrouter"),
        active_provider=ActiveLLMProvider.AUTO,
    )

    assert isinstance(provider, FallbackLLMProvider)
    assert provider.primary.name == "openrouter"
    assert provider.fallback.name == "yandex"


def test_yandex_override_selects_yandex_without_fallback_wrapper() -> None:
    provider = build_llm_provider(
        Settings(llm_primary_provider="openrouter"),
        active_provider=ActiveLLMProvider.YANDEX,
    )

    assert isinstance(provider, YandexAIStudioProvider)
    assert provider.name == "yandex"


def test_openrouter_override_selects_openrouter_without_fallback_wrapper() -> None:
    provider = build_llm_provider(
        Settings(llm_primary_provider="yandex"),
        active_provider=ActiveLLMProvider.OPENROUTER,
    )

    assert isinstance(provider, OpenRouterProvider)
    assert provider.name == "openrouter"
