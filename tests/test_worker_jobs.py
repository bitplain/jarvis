from datetime import UTC, datetime
from types import SimpleNamespace

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
    WebSearchProviderName,
    WebSearchSettings,
)
from app.services.web_search.types import SearchResult, WebSearchResponse, WebSearchStatus
from app.workers import jobs
from app.workers.arq_settings import WorkerSettings
from app.workers.jobs import process_llm_message, try_send_chat_action


class FailingBot:
    async def send_chat_action(self, *, chat_id: int, action: object) -> None:
        raise RuntimeError("flood control")


@pytest.mark.asyncio
async def test_try_send_chat_action_does_not_raise() -> None:
    await try_send_chat_action(FailingBot(), chat_id=1)


def test_daily_brief_worker_is_registered() -> None:
    assert jobs.deliver_daily_briefs in WorkerSettings.functions
    assert any(
        getattr(cron_job, "coroutine", None) is jobs.deliver_daily_briefs
        or getattr(cron_job, "name", "") == "cron:deliver_daily_briefs"
        for cron_job in WorkerSettings.cron_jobs
    )


def test_helpdesk_ticket_reminder_worker_is_registered() -> None:
    assert jobs.remind_helpdesk_tickets in WorkerSettings.functions
    assert any(
        getattr(cron_job, "coroutine", None) is jobs.remind_helpdesk_tickets
        or getattr(cron_job, "name", "") == "cron:remind_helpdesk_tickets"
        for cron_job in WorkerSettings.cron_jobs
    )


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


class HtmlFailingBot(FakeBot):
    async def send_message(self, *, chat_id: int, text: str, **kwargs: object) -> None:
        if kwargs.get("parse_mode") == "HTML":
            raise RuntimeError("bad html")
        await super().send_message(chat_id=chat_id, text=text, **kwargs)


class FailingSendBot(FakeBot):
    async def send_message(self, *, chat_id: int, text: str, **kwargs: object) -> None:
        del chat_id, text, kwargs
        raise RuntimeError("telegram unavailable")


class FakeProvider:
    def __init__(self) -> None:
        self.complete_called = False
        self.stream_called = False
        self.messages: list[list[LLMMessage]] = []

    async def complete(self, messages: list[LLMMessage]) -> LLMResponse:
        self.complete_called = True
        self.messages.append(messages)
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


class FakeHelpdeskTicketRepository:
    instances: list["FakeHelpdeskTicketRepository"] = []

    def __init__(self, session: object) -> None:
        del session
        self.reminded: list[str] = []
        self.items = [
            SimpleNamespace(
                id="ticket-1",
                glpi_ticket_id="0047513",
                latest_event_id=None,
                title="Выход <нового> сотрудника",
                status="waiting_ack",
                telegram_chat_id=-100123,
                assigned_by_user_id=None,
                assigned_at=None,
                done_at=None,
                next_reminder_at=datetime(2026, 6, 29, 9, 0, tzinfo=UTC),
                last_reminded_at=None,
                reminder_interval_minutes=10,
                created_at=datetime(2026, 6, 29, 8, 50, tzinfo=UTC),
                updated_at=datetime(2026, 6, 29, 8, 50, tzinfo=UTC),
            )
        ]
        self.__class__.instances.append(self)

    async def due_reminders(self, now: object, *, limit: int) -> list[object]:
        del now, limit
        return list(self.items)

    async def mark_reminded(self, item_id: str, *, now: object) -> object | None:
        del now
        self.reminded.append(item_id)
        return self.items[0]


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

    async def get_web_search_settings(
        self,
        *,
        default_provider: str = "disabled",
        default_max_results: int = 5,
    ) -> WebSearchSettings:
        del default_provider, default_max_results
        return WebSearchSettings(
            enabled=True,
            provider=WebSearchProviderName.TAVILY,
            max_results=5,
        )

    async def get_lists_timezone(self) -> object:
        from zoneinfo import ZoneInfo

        return ZoneInfo("Europe/Moscow")


class FakeDailyBriefRepository:
    instances: list["FakeDailyBriefRepository"] = []

    def __init__(self, session: object) -> None:
        del session
        self.marked: list[tuple[str, object]] = []
        self.__class__.instances.append(self)

    async def due_for_delivery(self, now: object) -> list[object]:
        del now
        return [
            SimpleNamespace(
                id="brief-settings-1",
                scope_type="private",
                chat_id=100500,
                user_id=100500,
                timezone="Europe/Moscow",
            )
        ]

    async def mark_sent_if_due(self, settings_id: str, local_date: object) -> bool:
        self.marked.append((settings_id, local_date))
        return True


class FakeDailyBriefService:
    def __init__(self, **kwargs: object) -> None:
        del kwargs

    async def build_brief(self, **kwargs: object) -> object:
        return kwargs


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.set_calls: list[tuple[str, int, bool]] = []
        self.deleted: list[str] = []

    async def set(self, key: str, value: str, *, ex: int, nx: bool) -> bool | None:
        self.set_calls.append((key, ex, nx))
        if nx and key in self.values:
            return None
        self.values[key] = value
        return True

    async def delete(self, key: str) -> None:
        self.deleted.append(key)
        self.values.pop(key, None)


class FakeWebSearchService:
    instances: list["FakeWebSearchService"] = []
    response = WebSearchResponse(
        WebSearchStatus.OK,
        [SearchResult("Railway changelog", "https://example.com/railway", "New release")],
    )

    def __init__(self) -> None:
        self.requests: list[object] = []
        self.__class__.instances.append(self)

    async def search(self, request: object) -> WebSearchResponse:
        self.requests.append(request)
        return self.__class__.response


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
async def test_worker_web_search_injects_context_and_appends_sources(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = FakeProvider()
    FakeBot.instances = []
    FakeMemoryService.instances = []
    FakeWebSearchService.instances = []
    FakeWebSearchService.response = WebSearchResponse(
        WebSearchStatus.OK,
        [
            SearchResult(
                "Railway changelog",
                "https://example.com/railway",
                "Latest Railway deploy update",
            )
        ],
    )
    monkeypatch.setattr(jobs, "Bot", FakeBot)
    monkeypatch.setattr(
        jobs,
        "get_settings",
        lambda: Settings(
            telegram_bot_token="123456:secret-token",
            memory_max_messages=5,
            streaming_group_fallback_enabled=True,
        ),
    )
    monkeypatch.setattr(jobs, "SessionLocal", FakeSessionLocal())
    monkeypatch.setattr(jobs, "MessageRepository", lambda session: object())
    monkeypatch.setattr(jobs, "RuntimeSettingRepository", lambda session: object())
    monkeypatch.setattr(jobs, "RuntimeSettingsService", FakeRuntimeSettingsService)
    monkeypatch.setattr(jobs, "MemoryService", FakeMemoryService)
    monkeypatch.setattr(jobs, "WebSearchCacheRepository", lambda session: object())
    monkeypatch.setattr(
        jobs,
        "build_web_search_service",
        lambda settings, *, provider_name, cache_repository: FakeWebSearchService(),
    )
    monkeypatch.setattr(
        jobs,
        "build_llm_provider",
        lambda settings, *, active_provider: provider,
    )
    caplog.set_level("INFO", logger="app.workers.jobs")

    await process_llm_message(
        {},
        {
            "chat_id": -100123,
            "user_id": 456,
            "private": False,
            "web_search": {"query": "последние обновления Railway"},
        },
    )

    bot = FakeBot.instances[0]
    memory = FakeMemoryService.instances[0]
    assert provider.complete_called is True
    assert provider.stream_called is False
    assert "Найденные источники" in memory.context_calls[0]["system_prompt"]
    assert "Latest Railway deploy update" in memory.context_calls[0]["system_prompt"]
    assert bot.sent_messages == [
        (
            -100123,
            "<b>Нашёл актуальные источники.</b>\n\n"
            "group answer\n\n"
            "<b>Источники:</b>\n"
            '1. <a href="https://example.com/railway">Railway changelog</a>',
        )
    ]
    assert bot.send_message_kwargs == {"parse_mode": "HTML"}
    assert memory.added[0]["text"] == bot.sent_messages[0][1]
    web_search_log = next(
        record for record in caplog.records if record.message == "web_search_completed"
    )
    assert not hasattr(web_search_log, "user_id")
    assert web_search_log.user_id_masked == "***456"


@pytest.mark.asyncio
async def test_worker_web_search_html_send_failure_falls_back_to_plain_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = FakeProvider()
    FakeBot.instances = []
    FakeMemoryService.instances = []
    FakeWebSearchService.instances = []
    FakeWebSearchService.response = WebSearchResponse(
        WebSearchStatus.OK,
        [
            SearchResult(
                "<Weather>",
                "https://example.com/weather",
                "<script>unsafe</script>",
            )
        ],
    )
    monkeypatch.setattr(jobs, "Bot", HtmlFailingBot)
    monkeypatch.setattr(
        jobs,
        "get_settings",
        lambda: Settings(telegram_bot_token="123456:secret-token", memory_max_messages=5),
    )
    monkeypatch.setattr(jobs, "SessionLocal", FakeSessionLocal())
    monkeypatch.setattr(jobs, "MessageRepository", lambda session: object())
    monkeypatch.setattr(jobs, "RuntimeSettingRepository", lambda session: object())
    monkeypatch.setattr(jobs, "RuntimeSettingsService", FakeRuntimeSettingsService)
    monkeypatch.setattr(jobs, "MemoryService", FakeMemoryService)
    monkeypatch.setattr(jobs, "WebSearchCacheRepository", lambda session: object())
    monkeypatch.setattr(
        jobs,
        "build_web_search_service",
        lambda settings, *, provider_name, cache_repository: FakeWebSearchService(),
    )
    monkeypatch.setattr(
        jobs,
        "build_llm_provider",
        lambda settings, *, active_provider: provider,
    )

    await process_llm_message(
        {},
        {
            "chat_id": 100500,
            "user_id": 456,
            "private": True,
            "web_search": {"query": "погода в Москве сегодня"},
        },
    )

    bot = FakeBot.instances[0]
    assert len(bot.sent_messages) == 1
    assert bot.sent_messages[0][0] == 100500
    assert "<b>" not in bot.sent_messages[0][1]
    assert "<script>" not in bot.sent_messages[0][1]
    assert "**" not in bot.sent_messages[0][1]
    assert bot.send_message_kwargs == {}


@pytest.mark.asyncio
async def test_worker_web_search_disabled_returns_message_without_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = FakeProvider()
    FakeBot.instances = []
    FakeMemoryService.instances = []

    class DisabledWebSearchRuntimeSettingsService(FakeRuntimeSettingsService):
        async def get_web_search_settings(
            self,
            *,
            default_provider: str = "disabled",
            default_max_results: int = 5,
        ) -> WebSearchSettings:
            del default_provider, default_max_results
            return WebSearchSettings(
                enabled=False,
                provider=WebSearchProviderName.DISABLED,
                max_results=5,
            )

    monkeypatch.setattr(jobs, "Bot", FakeBot)
    monkeypatch.setattr(
        jobs,
        "get_settings",
        lambda: Settings(telegram_bot_token="123456:secret-token", memory_max_messages=5),
    )
    monkeypatch.setattr(jobs, "SessionLocal", FakeSessionLocal())
    monkeypatch.setattr(jobs, "MessageRepository", lambda session: object())
    monkeypatch.setattr(jobs, "RuntimeSettingRepository", lambda session: object())
    monkeypatch.setattr(jobs, "RuntimeSettingsService", DisabledWebSearchRuntimeSettingsService)
    monkeypatch.setattr(jobs, "MemoryService", FakeMemoryService)
    monkeypatch.setattr(jobs, "WebSearchCacheRepository", lambda session: object())
    monkeypatch.setattr(
        jobs,
        "build_llm_provider",
        lambda settings, *, active_provider: provider,
    )

    await process_llm_message(
        {},
        {
            "chat_id": 100500,
            "user_id": 100500,
            "private": True,
            "web_search": {"query": "Railway"},
        },
    )

    bot = FakeBot.instances[0]
    assert provider.complete_called is False
    assert bot.sent_messages == [
        (100500, "Интернет-поиск выключен. Включите его в /settings -> Интернет-поиск.")
    ]


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
    monkeypatch.setattr(jobs, "utcnow", lambda: datetime(2026, 6, 26, 9, 0, tzinfo=UTC))

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
async def test_remind_helpdesk_tickets_sends_html_and_advances_after_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeBot.instances = []
    FakeHelpdeskTicketRepository.instances = []
    redis = FakeRedis()
    monkeypatch.setattr(jobs, "Bot", FakeBot)
    monkeypatch.setattr(
        jobs,
        "get_settings",
        lambda: Settings(telegram_bot_token="123456:secret-token"),
    )
    monkeypatch.setattr(jobs, "SessionLocal", FakeSessionLocal())
    monkeypatch.setattr(jobs, "HelpdeskTicketWorkItemRepository", FakeHelpdeskTicketRepository)
    monkeypatch.setattr(jobs, "utcnow", lambda: datetime(2026, 6, 29, 9, 0, tzinfo=UTC))

    await jobs.remind_helpdesk_tickets({"redis": redis})

    bot = FakeBot.instances[0]
    repository = FakeHelpdeskTicketRepository.instances[0]
    assert bot.sent_messages == [
        (
            -100123,
            "Новая заявка GLPI #0047513 ещё не взята в работу.\n\n"
            "<blockquote>Выход &lt;нового&gt; сотрудника</blockquote>",
        )
    ]
    assert bot.send_message_kwargs["parse_mode"] == "HTML"
    assert repository.reminded == ["ticket-1"]
    assert redis.set_calls == [("helpdesk_ticket:reminder:ticket-1", 120, True)]


@pytest.mark.asyncio
async def test_remind_helpdesk_tickets_send_failure_does_not_advance_reminder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeBot.instances = []
    FakeHelpdeskTicketRepository.instances = []
    monkeypatch.setattr(jobs, "Bot", FailingSendBot)
    monkeypatch.setattr(
        jobs,
        "get_settings",
        lambda: Settings(telegram_bot_token="123456:secret-token"),
    )
    monkeypatch.setattr(jobs, "SessionLocal", FakeSessionLocal())
    monkeypatch.setattr(jobs, "HelpdeskTicketWorkItemRepository", FakeHelpdeskTicketRepository)
    monkeypatch.setattr(jobs, "utcnow", lambda: datetime(2026, 6, 29, 9, 0, tzinfo=UTC))

    await jobs.remind_helpdesk_tickets({"redis": FakeRedis()})

    repository = FakeHelpdeskTicketRepository.instances[0]
    assert repository.reminded == []


@pytest.mark.asyncio
async def test_deliver_daily_briefs_skips_duplicate_redis_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeBot.instances = []
    FakeDailyBriefRepository.instances = []
    redis = FakeRedis()
    redis.values["daily_brief:send:brief-settings-1:2026-06-27"] = "1"
    monkeypatch.setattr(jobs, "Bot", FakeBot)
    monkeypatch.setattr(
        jobs,
        "get_settings",
        lambda: Settings(telegram_bot_token="123456:secret-token"),
    )
    monkeypatch.setattr(jobs, "SessionLocal", FakeSessionLocal())
    monkeypatch.setattr(jobs, "DailyBriefSettingsRepository", FakeDailyBriefRepository)
    monkeypatch.setattr(jobs, "DailyBriefService", FakeDailyBriefService)
    monkeypatch.setattr(jobs, "format_daily_brief_html", lambda brief: "daily brief")
    monkeypatch.setattr(jobs, "utcnow", lambda: datetime(2026, 6, 27, 6, 0, tzinfo=UTC))

    await jobs.deliver_daily_briefs({"redis": redis})

    bot = FakeBot.instances[0]
    repository = FakeDailyBriefRepository.instances[0]
    assert bot.sent_messages == []
    assert repository.marked == []
    assert redis.set_calls == [
        ("daily_brief:send:brief-settings-1:2026-06-27", 129600, True)
    ]
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
