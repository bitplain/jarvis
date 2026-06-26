import pytest

from app.services.runtime_settings_service import (
    ACTIVE_LLM_PROVIDER_KEY,
    DEFAULT_PROMPTS,
    PROMPT_GROUP_KEY,
    PROMPT_PRIVATE_KEY,
    PROMPT_WATCH_KEY,
    ActiveLLMProvider,
    PromptProfile,
    PromptProfileScope,
    PromptSource,
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

    async def delete_value(self, key: str) -> None:
        self.values.pop(key, None)


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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scope",
    [PromptProfileScope.PRIVATE, PromptProfileScope.GROUP, PromptProfileScope.WATCHER],
)
async def test_prompt_profile_defaults_to_balanced_when_setting_is_missing(
    scope: PromptProfileScope,
) -> None:
    service = RuntimeSettingsService(FakeRuntimeSettingsRepository())

    assert await service.get_prompt_profile(scope) == PromptProfile.BALANCED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scope", "key"),
    [
        (PromptProfileScope.PRIVATE, "prompt_profile_private"),
        (PromptProfileScope.GROUP, "prompt_profile_group"),
        (PromptProfileScope.WATCHER, "prompt_profile_watcher"),
    ],
)
async def test_prompt_profile_can_be_saved_per_scope(
    scope: PromptProfileScope,
    key: str,
) -> None:
    repository = FakeRuntimeSettingsRepository()
    service = RuntimeSettingsService(repository)

    saved = await service.set_prompt_profile(
        scope,
        PromptProfile.DEEP.value,
        updated_by_telegram_id=100500,
    )

    assert saved == PromptProfile.DEEP
    assert await service.get_prompt_profile(scope) == PromptProfile.DEEP
    assert repository.values[key] == PromptProfile.DEEP.value
    assert repository.updated_by[key] == 100500


@pytest.mark.asyncio
async def test_prompt_profile_rejects_unknown_value() -> None:
    service = RuntimeSettingsService(FakeRuntimeSettingsRepository())

    with pytest.raises(ValueError, match="unsupported_prompt_profile"):
        await service.set_prompt_profile(
            PromptProfileScope.PRIVATE,
            "mira",
            updated_by_telegram_id=100500,
        )


@pytest.mark.asyncio
async def test_prompt_profile_rejects_unknown_scope() -> None:
    service = RuntimeSettingsService(FakeRuntimeSettingsRepository())

    with pytest.raises(ValueError, match="unsupported_prompt_profile_scope"):
        await service.get_prompt_profile("secretary")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_prompt_profile_treats_invalid_database_value_as_balanced() -> None:
    repository = FakeRuntimeSettingsRepository()
    repository.values["prompt_profile_group"] = "broken"
    service = RuntimeSettingsService(repository)

    assert await service.get_prompt_profile(PromptProfileScope.GROUP) == PromptProfile.BALANCED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scope", "key"),
    [
        (PromptProfileScope.PRIVATE, PROMPT_PRIVATE_KEY),
        (PromptProfileScope.GROUP, PROMPT_GROUP_KEY),
        (PromptProfileScope.WATCHER, PROMPT_WATCH_KEY),
    ],
)
async def test_prompt_text_defaults_are_visible_per_scope(
    scope: PromptProfileScope,
    key: str,
) -> None:
    repository = FakeRuntimeSettingsRepository()
    service = RuntimeSettingsService(repository)

    prompt = await service.get_prompt(scope)

    assert key not in repository.values
    assert prompt.source is PromptSource.DEFAULT
    assert prompt.text == DEFAULT_PROMPTS[scope]


@pytest.mark.asyncio
async def test_custom_prompt_can_be_saved_and_reset() -> None:
    repository = FakeRuntimeSettingsRepository()
    service = RuntimeSettingsService(repository)

    saved = await service.set_prompt(
        PromptProfileScope.PRIVATE,
        "Ты Jarvis. Отвечай как тестовый private prompt.",
        updated_by_telegram_id=100500,
    )

    assert saved.source is PromptSource.CUSTOM
    assert saved.text == "Ты Jarvis. Отвечай как тестовый private prompt."
    assert repository.values[PROMPT_PRIVATE_KEY] == saved.text
    assert repository.updated_by[PROMPT_PRIVATE_KEY] == 100500

    reset = await service.reset_prompt(PromptProfileScope.PRIVATE)

    assert reset.source is PromptSource.DEFAULT
    assert reset.text == DEFAULT_PROMPTS[PromptProfileScope.PRIVATE]
    assert PROMPT_PRIVATE_KEY not in repository.values


@pytest.mark.asyncio
async def test_prompt_text_rejects_more_than_4000_characters() -> None:
    service = RuntimeSettingsService(FakeRuntimeSettingsRepository())

    with pytest.raises(ValueError, match="prompt_too_long"):
        await service.set_prompt(
            PromptProfileScope.PRIVATE,
            "я" * 4001,
            updated_by_telegram_id=100500,
        )
