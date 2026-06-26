from datetime import UTC, datetime

import pytest

from app.core.config import Settings
from app.llm.types import LLMMessage, LLMResponse, LLMStreamChunk
from app.services.reminder_service import StoredReminder
from app.services.runtime_settings_service import (
    DEFAULT_PROMPTS,
    ActiveLLMProvider,
    PromptProfile,
    PromptProfileScope,
    PromptSetting,
    PromptSource,
    RuntimeSettingsUnavailable,
)
from app.workers import jobs
from app.workers.jobs import process_llm_message, try_send_chat_action


class FailingBot:
    async def send_chat_action(self, *, chat_id: int, action: object) -> None:
        raise RuntimeError("flood control")


@pytest.mark.asyncio
async def test_try_send_chat_action_does_not_raise() -> None:
    await try_send_chat_action(FailingBot(), chat_id=1)


class FakeBot:
    instances: list["FakeBot"] = []

    def __init__(self, token: str) -> None:
        self.token = token
        self.chat_actions: list[tuple[int, object]] = []
        self.sent_messages: list[tuple[int, str]] = []
        self.session = self
        self.closed = False
        self.__class__.instances.append(self)

    async def send_chat_action(self, *, chat_id: int, action: object) -> None:
        self.chat_actions.append((chat_id, action))

    async def send_message(self, *, chat_id: int, text: str, **kwargs: object) -> None:
        self.sent_messages.append((chat_id, text))
        self.send_message_kwargs = kwargs

    async def close(self) -> None:
        self.closed = True


class FakeProvider:
    def __init__(self) -> None:
        self.complete_called = False
        self.stream_called = False

    async def complete(self, messages: list[LLMMessage]) -> LLMResponse:
        self.complete_called = True
        assert messages[-1].content == "group question"
        return LLMResponse(content="group answer", provider="test", model="test-model")

    async def stream(self, messages: list[LLMMessage]):
        del messages
        self.stream_called = True
        yield LLMStreamChunk(content="private draft", provider="test", model="test-model")


class FakeMemoryService:
    instances: list["FakeMemoryService"] = []

    def __init__(self, repository: object, *, max_messages: int) -> None:
        del repository, max_messages
        self.added: list[dict[str, object]] = []
        self.context_calls: list[dict[str, object]] = []
        self.__class__.instances.append(self)

    async def build_context(
        self,
        *,
        system_prompt: str | None = None,
        chat_id: int,
        prompt_profile: PromptProfile | None = None,
        chat_kind: str | None = None,
        household_memory: object | None = None,
        household_scope_type: str | None = None,
    ) -> list[LLMMessage]:
        del household_memory, household_scope_type
        self.context_calls.append(
            {
                "chat_id": chat_id,
                "system_prompt": system_prompt,
                "prompt_profile": prompt_profile,
                "chat_kind": chat_kind,
            }
        )
        return [
            LLMMessage(role="system", content="system"),
            LLMMessage(role="user", content="group question"),
        ]

    async def add_message(
        self,
        *,
        chat_id: int,
        user_id: int | None,
        role: object,
        text: str,
        telegram_message_id: int | None = None,
    ) -> None:
        self.added.append(
            {
                "chat_id": chat_id,
                "user_id": user_id,
                "role": role,
                "text": text,
                "telegram_message_id": telegram_message_id,
            }
        )


class FakeSessionContext:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


class FakeSessionLocal:
    def __call__(self) -> FakeSessionContext:
        return FakeSessionContext()


class FakeReminderRepository:
    instances: list["FakeReminderRepository"] = []

    def __init__(self, session: object) -> None:
        del session
        self.sent_ids: list[str] = []
        self.is_sent = False
        self.__class__.instances.append(self)

    async def due(self, now: object, *, limit: int) -> list[StoredReminder]:
        del now, limit
        if self.is_sent:
            return []
        return [
            StoredReminder(
                id="abc123",
                scope_type="private",
                chat_id=100500,
                user_id=100500,
                text="купить <молоко>",
                remind_at=datetime(2026, 6, 26, 9, 0, tzinfo=UTC),
                status="scheduled",
            )
        ]

    async def set_status(
        self,
        reminder_id: str,
        *,
        status: str,
        remind_at: object | None = None,
    ) -> StoredReminder | None:
        del remind_at
        if status == "sent":
            self.sent_ids.append(reminder_id)
            self.is_sent = True
        return None


class FakeRuntimeSettingsService:
    def __init__(self, repository: object) -> None:
        del repository

    async def get_active_llm_provider(self) -> ActiveLLMProvider:
        return ActiveLLMProvider.AUTO

    async def get_prompt_profile(self, scope: PromptProfileScope) -> PromptProfile:
        del scope
        return PromptProfile.BALANCED

    async def get_prompt(self, scope: PromptProfileScope) -> PromptSetting:
        return PromptSetting(scope=scope, text=DEFAULT_PROMPTS[scope], source=PromptSource.DEFAULT)

    async def get_lists_timezone(self) -> object:
        from zoneinfo import ZoneInfo

        return ZoneInfo("Europe/Moscow")


@pytest.mark.asyncio
async def test_worker_group_job_uses_send_message_without_private_streaming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = FakeProvider()
    FakeBot.instances = []
    FakeMemoryService.instances = []
    monkeypatch.setattr(jobs, "Bot", FakeBot)
    monkeypatch.setattr(
        jobs,
        "get_settings",
        lambda: Settings(
            telegram_bot_token="123456:secret-token",
            memory_max_messages=5,
            streaming_group_fallback_enabled=False,
        ),
    )
    monkeypatch.setattr(jobs, "SessionLocal", FakeSessionLocal())
    monkeypatch.setattr(jobs, "MessageRepository", lambda session: object())
    monkeypatch.setattr(jobs, "RuntimeSettingRepository", lambda session: object())
    monkeypatch.setattr(jobs, "RuntimeSettingsService", FakeRuntimeSettingsService)
    monkeypatch.setattr(jobs, "MemoryService", FakeMemoryService)
    monkeypatch.setattr(
        jobs,
        "build_llm_provider",
        lambda settings, *, active_provider: provider,
    )

    await process_llm_message(
        {},
        {"chat_id": -100123, "user_id": 456, "private": False},
    )

    bot = FakeBot.instances[0]
    memory = FakeMemoryService.instances[0]
    assert provider.complete_called is True
    assert provider.stream_called is False
    assert bot.sent_messages == [(-100123, "group answer")]
    assert memory.added[0]["chat_id"] == -100123
    assert memory.added[0]["user_id"] is None
    assert memory.added[0]["text"] == "group answer"
    assert bot.closed is True


@pytest.mark.asyncio
async def test_deliver_due_reminders_sends_html_and_marks_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeBot.instances = []
    FakeReminderRepository.instances = []
    monkeypatch.setattr(jobs, "Bot", FakeBot)
    monkeypatch.setattr(
        jobs,
        "get_settings",
        lambda: Settings(telegram_bot_token="123456:secret-token"),
    )
    monkeypatch.setattr(jobs, "SessionLocal", FakeSessionLocal())
    monkeypatch.setattr(jobs, "ReminderRepository", FakeReminderRepository)
    monkeypatch.setattr(jobs, "RuntimeSettingRepository", lambda session: object())
    monkeypatch.setattr(jobs, "RuntimeSettingsService", FakeRuntimeSettingsService)

    await jobs.deliver_due_reminders({})

    bot = FakeBot.instances[0]
    repository = FakeReminderRepository.instances[0]
    assert bot.sent_messages == [
        (
            100500,
            "<b>⏰ Напоминание</b>\n\n"
            "<blockquote>купить &lt;молоко&gt;</blockquote>\n"
            "Когда: <b>сегодня, 12:00</b>",
        )
    ]
    assert bot.send_message_kwargs == {"parse_mode": "HTML"}
    assert repository.sent_ids == ["abc123"]
    assert bot.closed is True


@pytest.mark.asyncio
async def test_worker_private_job_uses_private_prompt_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = FakeProvider()
    requested_scopes: list[PromptProfileScope] = []
    FakeBot.instances = []
    FakeMemoryService.instances = []

    class PrivateProfileRuntimeSettingsService:
        def __init__(self, repository: object) -> None:
            del repository

        async def get_active_llm_provider(self) -> ActiveLLMProvider:
            return ActiveLLMProvider.AUTO

        async def get_prompt_profile(self, scope: PromptProfileScope) -> PromptProfile:
            requested_scopes.append(scope)
            return PromptProfile.SHORT

        async def get_prompt(self, scope: PromptProfileScope) -> PromptSetting:
            requested_scopes.append(scope)
            return PromptSetting(
                scope=scope,
                text="CUSTOM PRIVATE RAW PROMPT",
                source=PromptSource.CUSTOM,
            )

    monkeypatch.setattr(jobs, "Bot", FakeBot)
    monkeypatch.setattr(
        jobs,
        "get_settings",
        lambda: Settings(
            telegram_bot_token="123456:secret-token",
            memory_max_messages=5,
        ),
    )
    monkeypatch.setattr(jobs, "SessionLocal", FakeSessionLocal())
    monkeypatch.setattr(jobs, "MessageRepository", lambda session: object())
    monkeypatch.setattr(jobs, "RuntimeSettingRepository", lambda session: object())
    monkeypatch.setattr(jobs, "RuntimeSettingsService", PrivateProfileRuntimeSettingsService)
    monkeypatch.setattr(jobs, "MemoryService", FakeMemoryService)
    monkeypatch.setattr(
        jobs,
        "build_llm_provider",
        lambda settings, *, active_provider: provider,
    )

    await process_llm_message(
        {},
        {"chat_id": 100500, "user_id": 100500, "private": True},
    )

    memory = FakeMemoryService.instances[0]
    assert requested_scopes == [PromptProfileScope.PRIVATE]
    assert memory.context_calls == [
        {
            "chat_id": 100500,
            "system_prompt": "CUSTOM PRIVATE RAW PROMPT",
            "prompt_profile": None,
            "chat_kind": None,
        }
    ]


@pytest.mark.asyncio
async def test_worker_group_job_uses_group_prompt_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = FakeProvider()
    requested_scopes: list[PromptProfileScope] = []
    FakeBot.instances = []
    FakeMemoryService.instances = []

    class GroupProfileRuntimeSettingsService:
        def __init__(self, repository: object) -> None:
            del repository

        async def get_active_llm_provider(self) -> ActiveLLMProvider:
            return ActiveLLMProvider.AUTO

        async def get_prompt_profile(self, scope: PromptProfileScope) -> PromptProfile:
            requested_scopes.append(scope)
            return PromptProfile.DEEP

        async def get_prompt(self, scope: PromptProfileScope) -> PromptSetting:
            requested_scopes.append(scope)
            return PromptSetting(
                scope=scope,
                text="CUSTOM GROUP RAW PROMPT",
                source=PromptSource.CUSTOM,
            )

    monkeypatch.setattr(jobs, "Bot", FakeBot)
    monkeypatch.setattr(
        jobs,
        "get_settings",
        lambda: Settings(
            telegram_bot_token="123456:secret-token",
            memory_max_messages=5,
            streaming_group_fallback_enabled=False,
        ),
    )
    monkeypatch.setattr(jobs, "SessionLocal", FakeSessionLocal())
    monkeypatch.setattr(jobs, "MessageRepository", lambda session: object())
    monkeypatch.setattr(jobs, "RuntimeSettingRepository", lambda session: object())
    monkeypatch.setattr(jobs, "RuntimeSettingsService", GroupProfileRuntimeSettingsService)
    monkeypatch.setattr(jobs, "MemoryService", FakeMemoryService)
    monkeypatch.setattr(
        jobs,
        "build_llm_provider",
        lambda settings, *, active_provider: provider,
    )

    await process_llm_message(
        {},
        {"chat_id": -100123, "user_id": 456, "private": False},
    )

    memory = FakeMemoryService.instances[0]
    assert requested_scopes == [PromptProfileScope.GROUP]
    assert memory.context_calls == [
        {
            "chat_id": -100123,
            "system_prompt": "CUSTOM GROUP RAW PROMPT",
            "prompt_profile": None,
            "chat_kind": None,
        }
    ]


@pytest.mark.asyncio
async def test_worker_reads_active_llm_provider_setting_for_each_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = FakeProvider()
    selected_providers: list[ActiveLLMProvider] = []
    FakeBot.instances = []
    FakeMemoryService.instances = []

    class FakeRuntimeSettingsService:
        def __init__(self, repository: object) -> None:
            del repository

        async def get_active_llm_provider(self) -> ActiveLLMProvider:
            return ActiveLLMProvider.OPENROUTER

        async def get_prompt_profile(self, scope: PromptProfileScope) -> PromptProfile:
            del scope
            return PromptProfile.BALANCED

        async def get_prompt(self, scope: PromptProfileScope) -> PromptSetting:
            return PromptSetting(
                scope=scope,
                text=DEFAULT_PROMPTS[scope],
                source=PromptSource.DEFAULT,
            )

    monkeypatch.setattr(jobs, "Bot", FakeBot)
    monkeypatch.setattr(
        jobs,
        "get_settings",
        lambda: Settings(
            telegram_bot_token="123456:secret-token",
            memory_max_messages=5,
            streaming_group_fallback_enabled=False,
        ),
    )
    monkeypatch.setattr(jobs, "SessionLocal", FakeSessionLocal())
    monkeypatch.setattr(jobs, "MessageRepository", lambda session: object())
    monkeypatch.setattr(jobs, "RuntimeSettingRepository", lambda session: object())
    monkeypatch.setattr(jobs, "RuntimeSettingsService", FakeRuntimeSettingsService)
    monkeypatch.setattr(jobs, "MemoryService", FakeMemoryService)

    def build_provider(settings: Settings, *, active_provider: ActiveLLMProvider) -> FakeProvider:
        del settings
        selected_providers.append(active_provider)
        return provider

    monkeypatch.setattr(jobs, "build_llm_provider", build_provider)

    await process_llm_message(
        {},
        {"chat_id": -100123, "user_id": 456, "private": False},
    )

    assert selected_providers == [ActiveLLMProvider.OPENROUTER]


@pytest.mark.asyncio
async def test_worker_falls_back_to_auto_when_runtime_settings_table_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = FakeProvider()
    selected_providers: list[ActiveLLMProvider] = []
    FakeBot.instances = []
    FakeMemoryService.instances = []

    class MissingTableRuntimeSettingsService:
        def __init__(self, repository: object) -> None:
            del repository

        async def get_active_llm_provider(self) -> ActiveLLMProvider:
            raise RuntimeSettingsUnavailable("runtime_settings_unavailable")

        async def get_prompt_profile(self, scope: PromptProfileScope) -> PromptProfile:
            del scope
            raise RuntimeSettingsUnavailable("runtime_settings_unavailable")

        async def get_prompt(self, scope: PromptProfileScope) -> PromptSetting:
            del scope
            raise RuntimeSettingsUnavailable("runtime_settings_unavailable")

    monkeypatch.setattr(jobs, "Bot", FakeBot)
    monkeypatch.setattr(
        jobs,
        "get_settings",
        lambda: Settings(
            telegram_bot_token="123456:secret-token",
            memory_max_messages=5,
            streaming_group_fallback_enabled=False,
        ),
    )
    monkeypatch.setattr(jobs, "SessionLocal", FakeSessionLocal())
    monkeypatch.setattr(jobs, "MessageRepository", lambda session: object())
    monkeypatch.setattr(jobs, "RuntimeSettingRepository", lambda session: object())
    monkeypatch.setattr(jobs, "RuntimeSettingsService", MissingTableRuntimeSettingsService)
    monkeypatch.setattr(jobs, "MemoryService", FakeMemoryService)

    def build_provider(settings: Settings, *, active_provider: ActiveLLMProvider) -> FakeProvider:
        del settings
        selected_providers.append(active_provider)
        return provider

    monkeypatch.setattr(jobs, "build_llm_provider", build_provider)

    await process_llm_message(
        {},
        {"chat_id": -100123, "user_id": 456, "private": False},
    )

    assert selected_providers == [ActiveLLMProvider.AUTO]
    assert provider.complete_called is True
    memory = FakeMemoryService.instances[0]
    assert memory.context_calls[0]["system_prompt"] == DEFAULT_PROMPTS[PromptProfileScope.GROUP]


@pytest.mark.asyncio
async def test_prompt_profile_db_error_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = FakeProvider()
    FakeBot.instances = []
    FakeMemoryService.instances = []

    class PromptProfileUnavailableRuntimeSettingsService:
        def __init__(self, repository: object) -> None:
            del repository

        async def get_active_llm_provider(self) -> ActiveLLMProvider:
            return ActiveLLMProvider.AUTO

        async def get_prompt_profile(self, scope: PromptProfileScope) -> PromptProfile:
            del scope
            raise RuntimeSettingsUnavailable("runtime_settings_unavailable")

        async def get_prompt(self, scope: PromptProfileScope) -> PromptSetting:
            del scope
            raise RuntimeSettingsUnavailable("runtime_settings_unavailable")

    monkeypatch.setattr(jobs, "Bot", FakeBot)
    monkeypatch.setattr(
        jobs,
        "get_settings",
        lambda: Settings(
            telegram_bot_token="123456:secret-token",
            memory_max_messages=5,
            streaming_group_fallback_enabled=False,
        ),
    )
    monkeypatch.setattr(jobs, "SessionLocal", FakeSessionLocal())
    monkeypatch.setattr(jobs, "MessageRepository", lambda session: object())
    monkeypatch.setattr(jobs, "RuntimeSettingRepository", lambda session: object())
    monkeypatch.setattr(
        jobs,
        "RuntimeSettingsService",
        PromptProfileUnavailableRuntimeSettingsService,
    )
    monkeypatch.setattr(jobs, "MemoryService", FakeMemoryService)
    monkeypatch.setattr(
        jobs,
        "build_llm_provider",
        lambda settings, *, active_provider: provider,
    )

    await process_llm_message(
        {},
        {"chat_id": 100500, "user_id": 100500, "private": True},
    )

    memory = FakeMemoryService.instances[0]
    assert memory.context_calls == [
        {
            "chat_id": 100500,
            "system_prompt": DEFAULT_PROMPTS[PromptProfileScope.PRIVATE],
            "prompt_profile": None,
            "chat_kind": None,
        }
    ]
