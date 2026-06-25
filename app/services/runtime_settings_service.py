from enum import StrEnum
from typing import Protocol

ACTIVE_LLM_PROVIDER_KEY = "active_llm_provider"


class RuntimeSettingsUnavailable(Exception):
    pass


class ActiveLLMProvider(StrEnum):
    AUTO = "auto"
    YANDEX = "yandex"
    OPENROUTER = "openrouter"


class RuntimeSettingsRepositoryProtocol(Protocol):
    async def get_value(self, key: str) -> str | None:
        raise NotImplementedError

    async def set_value(
        self,
        key: str,
        value: str,
        *,
        updated_by_telegram_id: int | None,
    ) -> None:
        raise NotImplementedError


class RuntimeSettingsService:
    def __init__(self, repository: RuntimeSettingsRepositoryProtocol) -> None:
        self.repository = repository

    async def get_active_llm_provider(self) -> ActiveLLMProvider:
        raw_value = await self.repository.get_value(ACTIVE_LLM_PROVIDER_KEY)
        if raw_value is None:
            return ActiveLLMProvider.AUTO
        try:
            return ActiveLLMProvider(raw_value)
        except ValueError:
            return ActiveLLMProvider.AUTO

    async def set_active_llm_provider(
        self,
        value: str | ActiveLLMProvider,
        *,
        updated_by_telegram_id: int | None,
    ) -> ActiveLLMProvider:
        try:
            provider = ActiveLLMProvider(value)
        except ValueError as exc:
            raise ValueError("unsupported_active_llm_provider") from exc
        await self.repository.set_value(
            ACTIVE_LLM_PROVIDER_KEY,
            provider.value,
            updated_by_telegram_id=updated_by_telegram_id,
        )
        return provider
