import pytest

from app.services.runtime_settings_service import (
    ACTIVE_LLM_PROVIDER_KEY,
    ActiveLLMProvider,
    RuntimeSettingsService,
)


class FakeRuntimeSettingsRepository:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.updated_by: dict[str, int | None] = {}

    async def get_value(self, key: str) -> str | None:
        return self.values.get(key)

    async def set_value(
        self,
        key: str,
        value: str,
        *,
        updated_by_telegram_id: int | None,
    ) -> None:
        self.values[key] = value
        self.updated_by[key] = updated_by_telegram_id


@pytest.mark.asyncio
async def test_active_llm_provider_defaults_to_auto_when_setting_is_missing() -> None:
    service = RuntimeSettingsService(FakeRuntimeSettingsRepository())

    assert await service.get_active_llm_provider() == ActiveLLMProvider.AUTO


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider",
    [ActiveLLMProvider.AUTO, ActiveLLMProvider.YANDEX, ActiveLLMProvider.OPENROUTER],
)
async def test_active_llm_provider_can_be_saved(provider: ActiveLLMProvider) -> None:
    repository = FakeRuntimeSettingsRepository()
    service = RuntimeSettingsService(repository)

    await service.set_active_llm_provider(provider.value, updated_by_telegram_id=100500)

    assert await service.get_active_llm_provider() == provider
    assert repository.values[ACTIVE_LLM_PROVIDER_KEY] == provider.value
    assert repository.updated_by[ACTIVE_LLM_PROVIDER_KEY] == 100500


@pytest.mark.asyncio
async def test_active_llm_provider_rejects_unknown_value() -> None:
    service = RuntimeSettingsService(FakeRuntimeSettingsRepository())

    with pytest.raises(ValueError, match="unsupported_active_llm_provider"):
        await service.set_active_llm_provider("anthropic", updated_by_telegram_id=100500)


@pytest.mark.asyncio
async def test_active_llm_provider_treats_invalid_database_value_as_auto() -> None:
    repository = FakeRuntimeSettingsRepository()
    repository.values[ACTIVE_LLM_PROVIDER_KEY] = "broken"
    service = RuntimeSettingsService(repository)

    assert await service.get_active_llm_provider() == ActiveLLMProvider.AUTO
