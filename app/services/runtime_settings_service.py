from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ACTIVE_LLM_PROVIDER_KEY = "active_llm_provider"
PROMPT_PROFILE_PRIVATE_KEY = "prompt_profile_private"
PROMPT_PROFILE_GROUP_KEY = "prompt_profile_group"
PROMPT_PROFILE_WATCHER_KEY = "prompt_profile_watcher"
PROMPT_PRIVATE_KEY = "prompt.private"
PROMPT_GROUP_KEY = "prompt.group"
PROMPT_WATCH_KEY = "prompt.watch"
LISTS_TIMEZONE_KEY = "lists.timezone"
WEB_SEARCH_ENABLED_KEY = "web_search.enabled"
WEB_SEARCH_PROVIDER_KEY = "web_search.provider"
WEB_SEARCH_MAX_RESULTS_KEY = "web_search.max_results"
DEFAULT_LISTS_TIMEZONE = "Europe/Moscow"
DEFAULT_WEB_SEARCH_MAX_RESULTS = 5
MAX_PROMPT_LENGTH = 4000


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


class PromptSource(StrEnum):
    DEFAULT = "default"
    CUSTOM = "custom"


class WebSearchProviderName(StrEnum):
    DISABLED = "disabled"
    TAVILY = "tavily"
    BRAVE = "brave"


@dataclass(frozen=True)
class PromptSetting:
    scope: PromptProfileScope
    text: str
    source: PromptSource


@dataclass(frozen=True)
class WebSearchSettings:
    enabled: bool
    provider: WebSearchProviderName
    max_results: int


PROMPT_PROFILE_KEYS = {
    PromptProfileScope.PRIVATE: PROMPT_PROFILE_PRIVATE_KEY,
    PromptProfileScope.GROUP: PROMPT_PROFILE_GROUP_KEY,
    PromptProfileScope.WATCHER: PROMPT_PROFILE_WATCHER_KEY,
}
PROMPT_KEYS = {
    PromptProfileScope.PRIVATE: PROMPT_PRIVATE_KEY,
    PromptProfileScope.GROUP: PROMPT_GROUP_KEY,
    PromptProfileScope.WATCHER: PROMPT_WATCH_KEY,
}
DEFAULT_PROMPTS = {
    PromptProfileScope.PRIVATE: (
        "Ты Jarvis. Отвечай только на русском языке. "
        "Отвечай кратко, полезно и структурированно. "
        "Если не знаешь ответ, честно скажи, что не знаешь. Не выдумывай факты. "
        "Контекст пришёл в личном чате с пользователем."
    ),
    PromptProfileScope.GROUP: (
        "Ты Jarvis. Отвечай только на русском языке. "
        "Отвечай кратко, полезно и структурированно. "
        "Если не знаешь ответ, честно скажи, что не знаешь. Не выдумывай факты. "
        "Контекст пришёл в групповом чате; отвечай только на переданный запрос "
        "и не делай вид, что видишь всю историю группы."
    ),
    PromptProfileScope.WATCHER: (
        "Ты Jarvis. Отвечай только на русском языке. "
        "Если не знаешь ответ, честно скажи, что не знаешь. Не выдумывай факты. "
        "Это заготовка для будущего watcher; автономные действия запрещены."
    ),
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

    async def delete_value(self, key: str) -> None:
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
        return PROMPT_PROFILE_KEYS[self._prompt_scope(scope)]

    def _prompt_scope(self, scope: str | PromptProfileScope) -> PromptProfileScope:
        try:
            return PromptProfileScope(scope)
        except ValueError as exc:
            raise ValueError("unsupported_prompt_profile_scope") from exc

    def _prompt_key(self, scope: str | PromptProfileScope) -> str:
        return PROMPT_KEYS[self._prompt_scope(scope)]

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

    async def get_prompt(self, scope: str | PromptProfileScope) -> PromptSetting:
        prompt_scope = self._prompt_scope(scope)
        raw_value = await self.repository.get_value(PROMPT_KEYS[prompt_scope])
        if raw_value is None:
            return PromptSetting(
                scope=prompt_scope,
                text=DEFAULT_PROMPTS[prompt_scope],
                source=PromptSource.DEFAULT,
            )
        return PromptSetting(scope=prompt_scope, text=raw_value, source=PromptSource.CUSTOM)

    async def set_prompt(
        self,
        scope: str | PromptProfileScope,
        value: str,
        *,
        updated_by_telegram_id: int | None,
    ) -> PromptSetting:
        prompt_scope = self._prompt_scope(scope)
        if len(value) > MAX_PROMPT_LENGTH:
            raise ValueError("prompt_too_long")
        await self.repository.set_value(
            PROMPT_KEYS[prompt_scope],
            value,
            updated_by_telegram_id=updated_by_telegram_id,
        )
        return PromptSetting(scope=prompt_scope, text=value, source=PromptSource.CUSTOM)

    async def reset_prompt(self, scope: str | PromptProfileScope) -> PromptSetting:
        prompt_scope = self._prompt_scope(scope)
        await self.repository.delete_value(PROMPT_KEYS[prompt_scope])
        return PromptSetting(
            scope=prompt_scope,
            text=DEFAULT_PROMPTS[prompt_scope],
            source=PromptSource.DEFAULT,
        )

    async def get_lists_timezone(self) -> ZoneInfo:
        raw_value = await self.repository.get_value(LISTS_TIMEZONE_KEY)
        if raw_value is None:
            return ZoneInfo(DEFAULT_LISTS_TIMEZONE)
        try:
            return ZoneInfo(raw_value)
        except ZoneInfoNotFoundError:
            return ZoneInfo(DEFAULT_LISTS_TIMEZONE)

    async def get_web_search_settings(
        self,
        *,
        default_provider: str = "disabled",
        default_max_results: int = DEFAULT_WEB_SEARCH_MAX_RESULTS,
    ) -> WebSearchSettings:
        enabled_raw = await self.repository.get_value(WEB_SEARCH_ENABLED_KEY)
        provider_raw = await self.repository.get_value(WEB_SEARCH_PROVIDER_KEY)
        max_results_raw = await self.repository.get_value(WEB_SEARCH_MAX_RESULTS_KEY)
        enabled = enabled_raw == "true"
        try:
            provider = WebSearchProviderName(provider_raw or default_provider)
        except ValueError:
            provider = WebSearchProviderName.DISABLED
        try:
            max_results = int(max_results_raw or default_max_results)
        except ValueError:
            max_results = default_max_results
        return WebSearchSettings(
            enabled=enabled,
            provider=provider,
            max_results=max(1, min(max_results, 10)),
        )

    async def set_web_search_enabled(
        self,
        enabled: bool,
        *,
        updated_by_telegram_id: int | None,
    ) -> WebSearchSettings:
        await self.repository.set_value(
            WEB_SEARCH_ENABLED_KEY,
            "true" if enabled else "false",
            updated_by_telegram_id=updated_by_telegram_id,
        )
        return await self.get_web_search_settings()

    async def set_web_search_provider(
        self,
        value: str | WebSearchProviderName,
        *,
        updated_by_telegram_id: int | None,
    ) -> WebSearchProviderName:
        try:
            provider = WebSearchProviderName(value)
        except ValueError as exc:
            raise ValueError("unsupported_web_search_provider") from exc
        await self.repository.set_value(
            WEB_SEARCH_PROVIDER_KEY,
            provider.value,
            updated_by_telegram_id=updated_by_telegram_id,
        )
        return provider

    async def set_web_search_max_results(
        self,
        value: int,
        *,
        updated_by_telegram_id: int | None,
    ) -> int:
        max_results = max(1, min(int(value), 10))
        await self.repository.set_value(
            WEB_SEARCH_MAX_RESULTS_KEY,
            str(max_results),
            updated_by_telegram_id=updated_by_telegram_id,
        )
        return max_results

    async def set_lists_timezone(
        self,
        value: str,
        *,
        updated_by_telegram_id: int | None,
    ) -> ZoneInfo:
        normalized = value.strip()
        try:
            timezone = ZoneInfo(normalized)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("unsupported_lists_timezone") from exc
        await self.repository.set_value(
            LISTS_TIMEZONE_KEY,
            normalized,
            updated_by_telegram_id=updated_by_telegram_id,
        )
        return timezone
