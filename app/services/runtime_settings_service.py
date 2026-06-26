from enum import StrEnum
from typing import Protocol

ACTIVE_LLM_PROVIDER_KEY = "active_llm_provider"
PROMPT_PROFILE_PRIVATE_KEY = "prompt_profile_private"
PROMPT_PROFILE_GROUP_KEY = "prompt_profile_group"
PROMPT_PROFILE_WATCHER_KEY = "prompt_profile_watcher"


class RuntimeSettingsUnavailable(Exception):
    pass


class ActiveLLMProvider(StrEnum):
    AUTO = "auto"
    YANDEX = "yandex"
    OPENROUTER = "openrouter"


class PromptProfile(StrEnum):
    BALANCED = "balanced"
    SHORT = "short"
    DEEP = "deep"
    DRAFT = "draft"
    WATCHER = "watcher"


class PromptProfileScope(StrEnum):
    PRIVATE = "private"
    GROUP = "group"
    WATCHER = "watcher"


PROMPT_PROFILE_KEYS = {
    PromptProfileScope.PRIVATE: PROMPT_PROFILE_PRIVATE_KEY,
    PromptProfileScope.GROUP: PROMPT_PROFILE_GROUP_KEY,
    PromptProfileScope.WATCHER: PROMPT_PROFILE_WATCHER_KEY,
}


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

    def _prompt_profile_key(self, scope: str | PromptProfileScope) -> str:
        try:
            prompt_scope = PromptProfileScope(scope)
        except ValueError as exc:
            raise ValueError("unsupported_prompt_profile_scope") from exc
        return PROMPT_PROFILE_KEYS[prompt_scope]

    async def get_prompt_profile(
        self,
        scope: str | PromptProfileScope,
    ) -> PromptProfile:
        raw_value = await self.repository.get_value(self._prompt_profile_key(scope))
        if raw_value is None:
            return PromptProfile.BALANCED
        try:
            return PromptProfile(raw_value)
        except ValueError:
            return PromptProfile.BALANCED

    async def set_prompt_profile(
        self,
        scope: str | PromptProfileScope,
        value: str | PromptProfile,
        *,
        updated_by_telegram_id: int | None,
    ) -> PromptProfile:
        try:
            profile = PromptProfile(value)
        except ValueError as exc:
            raise ValueError("unsupported_prompt_profile") from exc
        await self.repository.set_value(
            self._prompt_profile_key(scope),
            profile.value,
            updated_by_telegram_id=updated_by_telegram_id,
        )
        return profile
