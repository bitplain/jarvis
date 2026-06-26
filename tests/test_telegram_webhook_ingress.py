import logging
from collections.abc import AsyncIterator
from itertools import count
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import routes_telegram
from app.bot.middlewares import access
from app.bot.routers import commands, groups, lists_reminders, private
from app.core.config import Settings
from app.core.config import get_settings as app_get_settings
from app.db.models import MessageRole
from app.main import create_app
from app.services.reminder_service import InMemoryReminderRepository
from app.services.runtime_settings_service import (
    DEFAULT_PROMPTS,
    PromptProfile,
    PromptProfileScope,
    PromptSetting,
    PromptSource,
)
from app.services.shopping_service import InMemoryShoppingRepository
from app.services.telegram_access_service import AccessEntry

UPDATE_IDS = count(1000)


class FakeTelegramMessage:
    message_id = 9001


class FakeBotUser:
    id = 999
    username = "jarvis_bot"


class FakeBot:
    id = 999

    def __init__(self) -> None:
        self.sent_messages: list[dict[str, object]] = []
        self.edited_messages: list[dict[str, object]] = []
        self.callback_answers: list[dict[str, object]] = []
        self.chat_actions: list[dict[str, object]] = []

    async def __call__(self, method: object, **kwargs: object) -> FakeTelegramMessage:
        del kwargs
        method_name = method.__class__.__name__
        if method_name == "SendMessage":
            self.sent_messages.append(
                {
                    "chat_id": method.chat_id,  # type: ignore[attr-defined]
                    "text": method.text,  # type: ignore[attr-defined]
                    "parse_mode": getattr(method, "parse_mode", None),
                    "reply_markup": getattr(method, "reply_markup", None),
                }
            )
        if method_name == "EditMessageText":
            self.edited_messages.append(
                {
                    "chat_id": method.chat_id,  # type: ignore[attr-defined]
                    "message_id": method.message_id,  # type: ignore[attr-defined]
                    "text": method.text,  # type: ignore[attr-defined]
                    "parse_mode": getattr(method, "parse_mode", None),
                    "reply_markup": getattr(method, "reply_markup", None),
                }
            )
        if method_name == "AnswerCallbackQuery":
            self.callback_answers.append(
                {
                    "text": getattr(method, "text", None),
                    "show_alert": getattr(method, "show_alert", None),
                }
            )
        return FakeTelegramMessage()

    async def get_me(self) -> FakeBotUser:
        return FakeBotUser()

    async def me(self) -> FakeBotUser:
        return FakeBotUser()

    async def send_chat_action(self, **kwargs: object) -> None:
        self.chat_actions.append(kwargs)


class FakeRedis:
    def __init__(self) -> None:
        self.jobs: list[tuple[str, dict[str, Any]]] = []
        self.job_calls: list[dict[str, Any]] = []
        self.keys: dict[str, str] = {}

    async def enqueue_job(self, name: str, payload: dict[str, Any], **kwargs: Any) -> None:
        self.jobs.append((name, payload))
        self.job_calls.append({"name": name, "payload": payload, **kwargs})

    async def set(self, key: str, value: str, *, ex: int, nx: bool) -> bool | None:
        del ex
        if nx and key in self.keys:
            return None
        self.keys[key] = value
        return True


class BrokenRedisConnect(RuntimeError):
    pass


class BrokenDedupRedis(FakeRedis):
    async def set(self, key: str, value: str, *, ex: int, nx: bool) -> bool | None:
        del key, value, ex, nx
        raise BrokenRedisConnect("redis unavailable")


class FakeMessageRepository:
    def __init__(self, session: object) -> None:
        del session
        self.messages: list[dict[str, object]] = []

    async def add_message(
        self,
        *,
        chat_id: int,
        user_id: int | None,
        role: MessageRole,
        text: str,
        telegram_message_id: int | None = None,
    ) -> None:
        self.messages.append(
            {
                "chat_id": chat_id,
                "user_id": user_id,
                "role": role,
                "text": text,
                "telegram_message_id": telegram_message_id,
            }
        )

    async def recent_messages(self, *, chat_id: int, limit: int) -> list[object]:
        del chat_id, limit
        return []

    async def clear_chat(self, *, chat_id: int) -> None:
        del chat_id


class FakeAccessService:
    allowed_users: set[int] = set()
    allowed_groups: set[int] = set()
    raise_error: bool = False

    def __init__(self, repository: object, *, admin_ids: set[int]) -> None:
        del repository
        self.admin_ids = admin_ids

    def is_admin_user(self, user_id: int | None) -> bool:
        return user_id is not None and user_id in self.admin_ids

    async def is_allowed_user(self, user_id: int | None) -> bool:
        if self.raise_error:
            raise RuntimeError("access db unavailable")
        return user_id in self.allowed_users

    async def is_allowed_group(self, chat_id: int) -> bool:
        if self.raise_error:
            raise RuntimeError("access db unavailable")
        return not self.allowed_groups or chat_id in self.allowed_groups

    async def list_allowed_users(self) -> list[AccessEntry]:
        if self.raise_error:
            raise RuntimeError("access db unavailable")
        return [AccessEntry("user", user_id) for user_id in sorted(self.allowed_users)]

    async def list_allowed_groups(self) -> list[AccessEntry]:
        if self.raise_error:
            raise RuntimeError("access db unavailable")
        return [AccessEntry("group", chat_id) for chat_id in sorted(self.allowed_groups)]


class FakeRuntimeSettingsService:
    prompts: dict[PromptProfileScope, str] = {}
    lists_timezone: str | None = None

    def __init__(self, repository: object) -> None:
        del repository

    async def get_prompt_profile(self, scope: PromptProfileScope) -> PromptProfile:
        del scope
        return PromptProfile.BALANCED

    async def set_prompt_profile(
        self,
        scope: PromptProfileScope,
        value: str,
        *,
        updated_by_telegram_id: int | None,
    ) -> PromptProfile:
        del scope, updated_by_telegram_id
        return PromptProfile(value)

    async def get_prompt(self, scope: PromptProfileScope) -> PromptSetting:
        if scope in self.__class__.prompts:
            return PromptSetting(
                scope=scope,
                text=self.__class__.prompts[scope],
                source=PromptSource.CUSTOM,
            )
        return PromptSetting(scope=scope, text=DEFAULT_PROMPTS[scope], source=PromptSource.DEFAULT)

    async def set_prompt(
        self,
        scope: PromptProfileScope,
        value: str,
        *,
        updated_by_telegram_id: int | None,
    ) -> PromptSetting:
        del updated_by_telegram_id
        self.__class__.prompts[scope] = value
        return PromptSetting(scope=scope, text=value, source=PromptSource.CUSTOM)

    async def reset_prompt(self, scope: PromptProfileScope) -> PromptSetting:
        self.__class__.prompts.pop(scope, None)
        return PromptSetting(scope=scope, text=DEFAULT_PROMPTS[scope], source=PromptSource.DEFAULT)

    async def get_lists_timezone(self) -> object:
        from zoneinfo import ZoneInfo

        return ZoneInfo(self.__class__.lists_timezone or "Europe/Moscow")

    async def set_lists_timezone(
        self,
        value: str,
        *,
        updated_by_telegram_id: int | None,
    ) -> object:
        from zoneinfo import ZoneInfo

        del updated_by_telegram_id
        timezone = ZoneInfo(value)
        self.__class__.lists_timezone = value
        return timezone


def private_update(
    *,
    user_id: int,
    text: str = "тест",
    update_id: int | None = None,
    message_id: int = 10,
) -> dict[str, object]:
    return {
        "update_id": next(UPDATE_IDS) if update_id is None else update_id,
        "message": {
            "message_id": message_id,
            "date": 1_700_000_000,
            "chat": {"id": user_id, "type": "private", "first_name": "User"},
            "from": {"id": user_id, "is_bot": False, "first_name": "User"},
            "text": text,
        },
    }


def callback_update(
    data: str,
    *,
    user_id: int = 100500,
    chat_id: int | None = None,
    chat_type: str = "private",
    update_id: int | None = None,
) -> dict[str, object]:
    chat_id = chat_id or user_id
    return {
        "update_id": next(UPDATE_IDS) if update_id is None else update_id,
        "callback_query": {
            "id": "callback-1",
            "from": {"id": user_id, "is_bot": False, "first_name": "User"},
            "message": {
                "message_id": 20,
                "date": 1_700_000_000,
                "chat": {"id": chat_id, "type": chat_type, "first_name": "User"},
                "from": {"id": 999, "is_bot": True, "first_name": "Jarvis"},
                "text": "Настройки Jarvis",
            },
            "chat_instance": "chat-instance",
            "data": data,
        },
    }


def group_update(
    *,
    user_id: int,
    chat_id: int = -100123,
    chat_type: str = "supergroup",
    text: str = "@jarvis_bot тест",
    reply_to_user_id: int | None = None,
    update_id: int | None = None,
    message_id: int = 11,
) -> dict[str, object]:
    message: dict[str, object] = {
        "message_id": message_id,
        "date": 1_700_000_000,
        "chat": {"id": chat_id, "type": chat_type, "title": "Test group"},
        "from": {"id": user_id, "is_bot": False, "first_name": "User"},
        "text": text,
    }
    if reply_to_user_id is not None:
        message["reply_to_message"] = {
            "message_id": 10,
            "date": 1_700_000_000,
            "chat": {"id": chat_id, "type": chat_type, "title": "Test group"},
            "from": {
                "id": reply_to_user_id,
                "is_bot": reply_to_user_id == 999,
                "first_name": "Bot",
            },
            "text": "предыдущее сообщение",
        }
    return {
        "update_id": next(UPDATE_IDS) if update_id is None else update_id,
        "message": message,
    }


def markup_button_texts(message: dict[str, object]) -> list[str]:
    markup = message.get("reply_markup")
    if markup is None:
        return []
    return [button.text for row in markup.inline_keyboard for button in row]  # type: ignore[attr-defined]


def markup_callback_data(message: dict[str, object]) -> list[str]:
    markup = message.get("reply_markup")
    if markup is None:
        return []
    return [button.callback_data for row in markup.inline_keyboard for button in row]  # type: ignore[attr-defined]


@pytest.fixture
def ingress_app(monkeypatch: pytest.MonkeyPatch) -> tuple[Any, FakeBot, FakeRedis]:
    settings = Settings(
        _env_file=None,
        telegram_bot_token="123456:secret-token",
        telegram_bot_username="jarvis_bot",
        admin_telegram_ids="100500",
    )
    fake_bot = FakeBot()
    fake_redis = FakeRedis()
    shopping_repository = InMemoryShoppingRepository()
    reminder_repository = InMemoryReminderRepository()

    async def fake_get_session() -> AsyncIterator[object]:
        yield object()

    app = create_app(settings=settings)
    app.state.bot = fake_bot
    app.state.redis_pool = fake_redis
    app.state.shopping_repository = shopping_repository
    app.dependency_overrides[app_get_settings] = lambda: settings
    app.dependency_overrides[routes_telegram.get_session] = fake_get_session
    monkeypatch.setattr(private, "MessageRepository", FakeMessageRepository)
    monkeypatch.setattr(groups, "MessageRepository", FakeMessageRepository)
    monkeypatch.setattr(access, "TelegramAccessRepository", lambda session: object())
    monkeypatch.setattr(access, "TelegramAccessService", FakeAccessService)
    monkeypatch.setattr(commands, "TelegramAccessRepository", lambda session: object())
    monkeypatch.setattr(commands, "TelegramAccessService", FakeAccessService)
    monkeypatch.setattr(commands, "RuntimeSettingsService", FakeRuntimeSettingsService)
    monkeypatch.setattr(lists_reminders, "ShoppingRepository", lambda session: shopping_repository)
    monkeypatch.setattr(lists_reminders, "ReminderRepository", lambda session: reminder_repository)
    FakeAccessService.allowed_users = set()
    FakeAccessService.allowed_groups = set()
    FakeAccessService.raise_error = False
    FakeRuntimeSettingsService.prompts = {}
    FakeRuntimeSettingsService.lists_timezone = None
    FakeBotUser.username = "jarvis_bot"
    return app, fake_bot, fake_redis


def test_route_map_contains_webhook_health_and_ready() -> None:
    app = create_app(settings=Settings(_env_file=None))
    paths = app.openapi()["paths"]

    assert "post" in paths["/telegram/webhook"]
    assert "get" in paths["/health"]
    assert "get" in paths["/ready"]


@pytest.mark.asyncio
async def test_webhook_private_admin_update_enqueues_once(
    ingress_app: tuple[Any, FakeBot, FakeRedis],
) -> None:
    app, bot, redis = ingress_app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/telegram/webhook", json=private_update(user_id=100500))

    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}
    assert redis.jobs == [
        ("process_llm_message", {"chat_id": 100500, "user_id": 100500, "private": True})
    ]
    assert [message["text"] for message in bot.sent_messages] == ["Думаю"]


@pytest.mark.asyncio
async def test_duplicate_private_update_id_is_accepted_without_second_enqueue(
    ingress_app: tuple[Any, FakeBot, FakeRedis],
    caplog: pytest.LogCaptureFixture,
) -> None:
    app, bot, redis = ingress_app
    update = private_update(user_id=100500, text="Привет", update_id=901, message_id=77)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first_response = await client.post("/telegram/webhook", json=update)
        second_response = await client.post("/telegram/webhook", json=update)

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert first_response.json() == {"status": "accepted"}
    assert second_response.json() == {"status": "accepted"}
    assert redis.jobs == [
        ("process_llm_message", {"chat_id": 100500, "user_id": 100500, "private": True})
    ]
    assert redis.job_calls[0]["job_id"] == "llm:100500:77"
    assert [message["text"] for message in bot.sent_messages] == ["Думаю"]
    assert "telegram_webhook_duplicate_update_skipped" in caplog.text
    assert "Привет" not in caplog.text


@pytest.mark.asyncio
async def test_duplicate_group_update_id_is_accepted_without_second_enqueue(
    ingress_app: tuple[Any, FakeBot, FakeRedis],
) -> None:
    app, bot, redis = ingress_app
    update = group_update(user_id=100500, update_id=902, message_id=88)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first_response = await client.post("/telegram/webhook", json=update)
        second_response = await client.post("/telegram/webhook", json=update)

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert redis.jobs == [
        ("process_llm_message", {"chat_id": -100123, "user_id": 100500, "private": False})
    ]
    assert redis.job_calls[0]["job_id"] == "llm:-100123:88"
    assert len(bot.chat_actions) == 1


@pytest.mark.asyncio
async def test_duplicate_start_update_id_is_accepted_without_second_reply(
    ingress_app: tuple[Any, FakeBot, FakeRedis],
) -> None:
    app, bot, redis = ingress_app
    update = private_update(user_id=100500, text="/start", update_id=903, message_id=89)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first_response = await client.post("/telegram/webhook", json=update)
        second_response = await client.post("/telegram/webhook", json=update)

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert redis.jobs == []
    assert [message["text"] for message in bot.sent_messages] == [
        "Jarvis готов. Пишите вопрос на русском языке."
    ]


@pytest.mark.asyncio
async def test_webhook_dedup_redis_failure_still_feeds_dispatcher(
    ingress_app: tuple[Any, FakeBot, FakeRedis],
    caplog: pytest.LogCaptureFixture,
) -> None:
    app, bot, _ = ingress_app
    broken_redis = BrokenDedupRedis()
    app.state.redis_pool = broken_redis

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/telegram/webhook",
            json=private_update(user_id=100500, text="Привет", update_id=904, message_id=90),
        )

    assert response.status_code == 200
    assert broken_redis.jobs == [
        ("process_llm_message", {"chat_id": 100500, "user_id": 100500, "private": True})
    ]
    assert [message["text"] for message in bot.sent_messages] == ["Думаю"]
    assert "telegram_webhook_dedup_unavailable" in caplog.text
    assert "Привет" not in caplog.text


@pytest.mark.asyncio
async def test_private_start_replies_after_prompt_profiles(
    ingress_app: tuple[Any, FakeBot, FakeRedis],
) -> None:
    app, bot, redis = ingress_app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/telegram/webhook",
            json=private_update(user_id=100500, text="/start"),
        )

    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}
    assert redis.jobs == []
    assert [message["text"] for message in bot.sent_messages] == [
        "Jarvis готов. Пишите вопрос на русском языке."
    ]


@pytest.mark.asyncio
async def test_private_start_replies_when_redis_pool_is_unavailable(
    ingress_app: tuple[Any, FakeBot, FakeRedis],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, bot, _ = ingress_app
    delattr(app.state, "redis_pool")

    async def broken_create_pool(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise BrokenRedisConnect("redis unavailable")

    monkeypatch.setattr(routes_telegram, "create_pool", broken_create_pool)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/telegram/webhook",
            json=private_update(user_id=100500, text="/start"),
        )

    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}
    assert [message["text"] for message in bot.sent_messages] == [
        "Jarvis готов. Пишите вопрос на русском языке."
    ]


@pytest.mark.asyncio
async def test_private_text_admin_enqueues_after_prompt_profiles(
    ingress_app: tuple[Any, FakeBot, FakeRedis],
) -> None:
    app, bot, redis = ingress_app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/telegram/webhook",
            json=private_update(user_id=100500, text="Привет"),
        )

    assert response.status_code == 200
    assert redis.jobs == [
        ("process_llm_message", {"chat_id": 100500, "user_id": 100500, "private": True})
    ]
    assert [message["text"] for message in bot.sent_messages] == ["Думаю"]


@pytest.mark.asyncio
async def test_private_shopping_add_returns_html_without_llm_job(
    ingress_app: tuple[Any, FakeBot, FakeRedis],
) -> None:
    app, bot, redis = ingress_app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/telegram/webhook",
            json=private_update(user_id=100500, text="добавь хлеб в список покупок"),
        )

    assert response.status_code == 200
    assert redis.jobs == []
    assert "<b>🛒 Список покупок</b>" in str(bot.sent_messages[0]["text"])
    assert "хлеб" in str(bot.sent_messages[0]["text"])
    assert bot.sent_messages[0]["parse_mode"] == "HTML"
    assert "➕ Добавить" in markup_button_texts(bot.sent_messages[0])


@pytest.mark.asyncio
async def test_private_buy_colon_adds_items_without_llm_job(
    ingress_app: tuple[Any, FakeBot, FakeRedis],
) -> None:
    app, bot, redis = ingress_app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/telegram/webhook",
            json=private_update(user_id=100500, text="Купить: хлеб сок мазик запеканку"),
        )

    assert response.status_code == 200
    assert redis.jobs == []
    repository = app.state.shopping_repository
    list_id = repository.scope_index[("private", 100500)]
    items = await repository.list_items(list_id)
    assert [item.text for item in items] == ["хлеб", "сок", "мазик", "запеканку"]
    assert "хлеб" in str(bot.sent_messages[0]["text"])
    assert "сок" in str(bot.sent_messages[0]["text"])
    assert "мазик" in str(bot.sent_messages[0]["text"])
    assert "запеканку" in str(bot.sent_messages[0]["text"])


@pytest.mark.asyncio
async def test_private_reminder_add_returns_html_without_llm_job(
    ingress_app: tuple[Any, FakeBot, FakeRedis],
) -> None:
    app, bot, redis = ingress_app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/telegram/webhook",
            json=private_update(user_id=100500, text="напомни через 30 минут проверить духовку"),
        )

    assert response.status_code == 200
    assert redis.jobs == []
    assert "<b>⏰ Напоминание создано</b>" in str(bot.sent_messages[0]["text"])
    assert "проверить духовку" in str(bot.sent_messages[0]["text"])


@pytest.mark.asyncio
async def test_settings_lists_reminders_screen_and_timezone_fsm(
    ingress_app: tuple[Any, FakeBot, FakeRedis],
) -> None:
    app, bot, redis = ingress_app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        settings_response = await client.post(
            "/telegram/webhook",
            json=callback_update("settings:lists"),
        )
        timezone_response = await client.post(
            "/telegram/webhook",
            json=callback_update("settings:lists:timezone"),
        )
        save_response = await client.post(
            "/telegram/webhook",
            json=private_update(user_id=100500, text="Europe/Amsterdam"),
        )

    assert settings_response.status_code == 200
    assert timezone_response.status_code == 200
    assert save_response.status_code == 200
    assert redis.jobs == []
    edited_texts = [str(message["text"]) for message in bot.edited_messages]
    sent_texts = [str(message["text"]) for message in bot.sent_messages]
    assert any("Списки и напоминания" in text for text in edited_texts)
    assert any("Часовой пояс: Europe/Moscow" in text for text in edited_texts)
    assert any("Отправьте часовой пояс" in text for text in edited_texts)
    assert FakeRuntimeSettingsService.lists_timezone == "Europe/Amsterdam"
    assert any("Часовой пояс сохранён: Europe/Amsterdam" in text for text in sent_texts)


@pytest.mark.asyncio
async def test_settings_lists_timezone_invalid_and_cancel_do_not_change_value(
    ingress_app: tuple[Any, FakeBot, FakeRedis],
) -> None:
    app, bot, redis = ingress_app
    FakeRuntimeSettingsService.lists_timezone = "Asia/Dubai"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/telegram/webhook", json=callback_update("settings:lists:timezone"))
        invalid_response = await client.post(
            "/telegram/webhook",
            json=private_update(user_id=100500, text="Europe/NoSuchCity"),
        )
        await client.post("/telegram/webhook", json=callback_update("settings:lists:timezone"))
        cancel_response = await client.post(
            "/telegram/webhook",
            json=private_update(user_id=100500, text="/cancel"),
        )

    assert invalid_response.status_code == 200
    assert cancel_response.status_code == 200
    assert redis.jobs == []
    assert FakeRuntimeSettingsService.lists_timezone == "Asia/Dubai"
    sent_texts = [str(message["text"]) for message in bot.sent_messages]
    assert any("Не знаю такой часовой пояс." in text for text in sent_texts)
    assert any("Изменение часового пояса отменено." in text for text in sent_texts)


@pytest.mark.asyncio
async def test_lists_help_private_and_group_do_not_enqueue_llm(
    ingress_app: tuple[Any, FakeBot, FakeRedis],
) -> None:
    app, bot, redis = ingress_app
    FakeBotUser.username = "Home_ai_my_bot"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        private_response = await client.post(
            "/telegram/webhook",
            json=private_update(user_id=100500, text="помощь список"),
        )
        group_response = await client.post(
            "/telegram/webhook",
            json=group_update(user_id=100500, text="@Home_ai_my_bot помощь напоминания"),
        )

    assert private_response.status_code == 200
    assert group_response.status_code == 200
    assert redis.jobs == []
    assert "Что я умею со списками и напоминаниями" in str(bot.sent_messages[0]["text"])
    assert "@Home_ai_my_bot добавь хлеб, молоко и яйца в список покупок" in str(
        bot.sent_messages[1]["text"]
    )
    assert bot.sent_messages[0]["parse_mode"] == "HTML"
    assert bot.sent_messages[1]["parse_mode"] == "HTML"


@pytest.mark.asyncio
async def test_shopping_add_button_fsm_adds_items_without_llm_job(
    ingress_app: tuple[Any, FakeBot, FakeRedis],
) -> None:
    app, bot, redis = ingress_app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        list_response = await client.post(
            "/telegram/webhook",
            json=private_update(user_id=100500, text="список"),
        )
        callbacks = markup_callback_data(bot.sent_messages[-1])
        add_callback = next(value for value in callbacks if value == "shop:add")
        callback_response = await client.post(
            "/telegram/webhook",
            json=callback_update(add_callback),
        )
        text_response = await client.post(
            "/telegram/webhook",
            json=private_update(user_id=100500, text="молоко, яйца"),
        )

    assert list_response.status_code == 200
    assert callback_response.status_code == 200
    assert text_response.status_code == 200
    assert redis.jobs == []
    edited_texts = [str(message["text"]) for message in bot.edited_messages]
    assert any("Что добавить в список покупок?" in text for text in edited_texts)
    assert "молоко" in str(bot.sent_messages[-1]["text"])
    assert "яйца" in str(bot.sent_messages[-1]["text"])
    assert "➕ Добавить" in markup_button_texts(bot.sent_messages[-1])


@pytest.mark.asyncio
async def test_group_shopping_add_button_fsm_strips_bot_mention(
    ingress_app: tuple[Any, FakeBot, FakeRedis],
) -> None:
    app, bot, redis = ingress_app
    FakeBotUser.username = "Home_ai_my_bot"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post(
            "/telegram/webhook",
            json=group_update(user_id=100500, text="@Home_ai_my_bot список"),
        )
        callbacks = markup_callback_data(bot.sent_messages[-1])
        add_callback = next(value for value in callbacks if value == "shop:add")
        callback_response = await client.post(
            "/telegram/webhook",
            json=callback_update(
                add_callback,
                user_id=100500,
                chat_id=-100123,
                chat_type="supergroup",
            ),
        )
        text_response = await client.post(
            "/telegram/webhook",
            json=group_update(
                user_id=100500,
                text="@Home_ai_my_bot творожок",
            ),
        )

    assert callback_response.status_code == 200
    assert text_response.status_code == 200
    assert redis.jobs == []
    final_text = str(bot.sent_messages[-1]["text"])
    assert "творожок" in final_text
    assert "@home_ai_my_bot творожок" not in final_text.lower()


@pytest.mark.asyncio
async def test_group_shopping_add_button_fsm_rejects_empty_after_mention(
    ingress_app: tuple[Any, FakeBot, FakeRedis],
) -> None:
    app, bot, redis = ingress_app
    FakeBotUser.username = "Home_ai_my_bot"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post(
            "/telegram/webhook",
            json=group_update(user_id=100500, text="@Home_ai_my_bot список"),
        )
        callbacks = markup_callback_data(bot.sent_messages[-1])
        add_callback = next(value for value in callbacks if value == "shop:add")
        await client.post(
            "/telegram/webhook",
            json=callback_update(
                add_callback,
                user_id=100500,
                chat_id=-100123,
                chat_type="supergroup",
            ),
        )
        text_response = await client.post(
            "/telegram/webhook",
            json=group_update(
                user_id=100500,
                text="@Home_ai_my_bot",
            ),
        )

    assert text_response.status_code == 200
    assert redis.jobs == []
    final_text = str(bot.sent_messages[-1]["text"])
    assert "Не понял, что добавить." in final_text
    assert "1." not in final_text


@pytest.mark.asyncio
async def test_shopping_clear_all_requires_confirmation_and_is_repeat_safe(
    ingress_app: tuple[Any, FakeBot, FakeRedis],
) -> None:
    app, bot, redis = ingress_app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post(
            "/telegram/webhook",
            json=private_update(user_id=100500, text="добавь молоко, яйца в список"),
        )
        clear_response = await client.post(
            "/telegram/webhook",
            json=callback_update("shop:clear_all"),
        )
        confirm_response = await client.post(
            "/telegram/webhook",
            json=callback_update("shop:clear_all_confirm"),
        )
        repeated_response = await client.post(
            "/telegram/webhook",
            json=callback_update("shop:clear_all_confirm"),
        )

    assert clear_response.status_code == 200
    assert confirm_response.status_code == 200
    assert repeated_response.status_code == 200
    assert redis.jobs == []
    edited_texts = [str(message["text"]) for message in bot.edited_messages]
    assert any("Точно очистить весь список покупок?" in text for text in edited_texts)
    assert "Список пуст." in str(bot.edited_messages[-1]["text"])


@pytest.mark.asyncio
async def test_reminder_add_button_fsm_creates_reminder_without_llm_job(
    ingress_app: tuple[Any, FakeBot, FakeRedis],
) -> None:
    app, bot, redis = ingress_app
    FakeRuntimeSettingsService.lists_timezone = "Europe/Amsterdam"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        list_response = await client.post(
            "/telegram/webhook",
            json=private_update(user_id=100500, text="напоминания"),
        )
        callbacks = markup_callback_data(bot.sent_messages[-1])
        add_callback = next(value for value in callbacks if value == "rem:add")
        callback_response = await client.post(
            "/telegram/webhook",
            json=callback_update(add_callback),
        )
        text_response = await client.post(
            "/telegram/webhook",
            json=private_update(user_id=100500, text="напомни завтра в 10 купить молоко"),
        )

    assert list_response.status_code == 200
    assert callback_response.status_code == 200
    assert text_response.status_code == 200
    assert redis.jobs == []
    assert any("Что напомнить и когда?" in str(message["text"]) for message in bot.edited_messages)
    assert "купить молоко" in str(bot.sent_messages[-1]["text"])
    assert "завтра, 10:00" in str(bot.sent_messages[-1]["text"])


@pytest.mark.asyncio
async def test_reminder_list_has_action_buttons_and_repeated_delete_is_safe(
    ingress_app: tuple[Any, FakeBot, FakeRedis],
) -> None:
    app, bot, redis = ingress_app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post(
            "/telegram/webhook",
            json=private_update(user_id=100500, text="напомни через 30 минут проверить доставку"),
        )
        list_response = await client.post(
            "/telegram/webhook",
            json=private_update(user_id=100500, text="покажи напоминания"),
        )
        callbacks = markup_callback_data(bot.sent_messages[-1])
        delete_callback = next(value for value in callbacks if value.startswith("rem:del:"))
        delete_response = await client.post(
            "/telegram/webhook",
            json=callback_update(delete_callback),
        )
        repeated_response = await client.post(
            "/telegram/webhook",
            json=callback_update(delete_callback),
        )

    assert list_response.status_code == 200
    assert delete_response.status_code == 200
    assert repeated_response.status_code == 200
    assert redis.jobs == []
    button_texts = markup_button_texts(bot.sent_messages[-1])
    assert "✅ Выполнено" in button_texts
    assert "⏰ +10 мин" in button_texts
    assert "⏰ +1 час" in button_texts
    assert "🗑 Удалить" in button_texts
    assert "➕ Добавить напоминание" in button_texts
    assert "Активных напоминаний нет." in str(bot.edited_messages[-1]["text"])


@pytest.mark.asyncio
async def test_private_mira_ingress_enqueues_without_regular_thinking_message(
    ingress_app: tuple[Any, FakeBot, FakeRedis],
) -> None:
    app, bot, redis = ingress_app
    settings = app.dependency_overrides[app_get_settings]()
    settings.streaming_enabled = True
    settings.streaming_private_draft_enabled = True
    settings.telegram_private_draft_streaming_enabled = True

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/telegram/webhook",
            json=private_update(user_id=100500, text="Привет"),
        )

    assert response.status_code == 200
    assert redis.jobs == [
        ("process_llm_message", {"chat_id": 100500, "user_id": 100500, "private": True})
    ]
    assert bot.sent_messages == []


@pytest.mark.asyncio
async def test_prompt_profile_fsm_does_not_capture_normal_private_text(
    ingress_app: tuple[Any, FakeBot, FakeRedis],
) -> None:
    app, bot, redis = ingress_app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        profile_response = await client.post(
            "/telegram/webhook",
            json=callback_update("settings:prompts:private"),
        )
        text_response = await client.post(
            "/telegram/webhook",
            json=private_update(user_id=100500, text="Привет"),
        )

    assert profile_response.status_code == 200
    assert text_response.status_code == 200
    assert redis.jobs == [
        ("process_llm_message", {"chat_id": 100500, "user_id": 100500, "private": True})
    ]
    assert [message["text"] for message in bot.sent_messages] == ["Думаю"]


@pytest.mark.asyncio
async def test_webhook_uses_persistent_dispatcher_for_prompt_profile_fsm(
    ingress_app: tuple[Any, FakeBot, FakeRedis],
) -> None:
    app, bot, redis = ingress_app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        profile_response = await client.post(
            "/telegram/webhook",
            json=callback_update("settings:prompt:private:edit"),
        )
        dispatcher = app.state.dispatcher
        text_response = await client.post(
            "/telegram/webhook",
            json=private_update(user_id=100500, text="Новый webhook prompt"),
        )

    assert profile_response.status_code == 200
    assert text_response.status_code == 200
    assert app.state.dispatcher is dispatcher
    assert redis.jobs == []
    assert FakeRuntimeSettingsService.prompts[PromptProfileScope.PRIVATE] == "Новый webhook prompt"
    assert any("Промт сохранён." in str(message["text"]) for message in bot.sent_messages)


@pytest.mark.asyncio
async def test_webhook_private_unauthorized_gets_access_denied_without_job(
    ingress_app: tuple[Any, FakeBot, FakeRedis],
) -> None:
    app, bot, redis = ingress_app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/telegram/webhook", json=private_update(user_id=42))

    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}
    assert redis.jobs == []
    assert [message["text"] for message in bot.sent_messages] == ["Доступ запрещён."]


@pytest.mark.asyncio
async def test_private_text_unknown_user_denied_after_prompt_profiles(
    ingress_app: tuple[Any, FakeBot, FakeRedis],
) -> None:
    app, bot, redis = ingress_app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/telegram/webhook",
            json=private_update(user_id=42, text="Привет"),
        )

    assert response.status_code == 200
    assert redis.jobs == []
    assert [message["text"] for message in bot.sent_messages] == ["Доступ запрещён."]


@pytest.mark.asyncio
async def test_webhook_private_db_allowed_user_enqueues_once(
    ingress_app: tuple[Any, FakeBot, FakeRedis],
) -> None:
    app, bot, redis = ingress_app
    FakeAccessService.allowed_users = {200600}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/telegram/webhook", json=private_update(user_id=200600))

    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}
    assert redis.jobs == [
        ("process_llm_message", {"chat_id": 200600, "user_id": 200600, "private": True})
    ]
    assert [message["text"] for message in bot.sent_messages] == ["Думаю"]


@pytest.mark.asyncio
async def test_private_text_allowed_user_enqueues_after_prompt_profiles(
    ingress_app: tuple[Any, FakeBot, FakeRedis],
) -> None:
    app, bot, redis = ingress_app
    FakeAccessService.allowed_users = {200600}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/telegram/webhook",
            json=private_update(user_id=200600, text="Привет"),
        )

    assert response.status_code == 200
    assert redis.jobs == [
        ("process_llm_message", {"chat_id": 200600, "user_id": 200600, "private": True})
    ]
    assert [message["text"] for message in bot.sent_messages] == ["Думаю"]


@pytest.mark.asyncio
async def test_webhook_group_admin_mention_enqueues_once(
    ingress_app: tuple[Any, FakeBot, FakeRedis],
) -> None:
    app, bot, redis = ingress_app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/telegram/webhook", json=group_update(user_id=100500))

    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}
    assert redis.jobs == [
        ("process_llm_message", {"chat_id": -100123, "user_id": 100500, "private": False})
    ]
    assert bot.sent_messages == []
    assert bot.chat_actions


@pytest.mark.asyncio
async def test_group_shopping_mention_returns_html_without_llm_job(
    ingress_app: tuple[Any, FakeBot, FakeRedis],
) -> None:
    app, bot, redis = ingress_app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/telegram/webhook",
            json=group_update(user_id=100500, text="@jarvis_bot добавь хлеб в список покупок"),
        )

    assert response.status_code == 200
    assert redis.jobs == []
    assert "<b>🛒 Список покупок</b>" in str(bot.sent_messages[0]["text"])
    assert "хлеб" in str(bot.sent_messages[0]["text"])
    assert bot.chat_actions == []


@pytest.mark.asyncio
async def test_group_buy_colon_mention_adds_item_without_llm_job(
    ingress_app: tuple[Any, FakeBot, FakeRedis],
) -> None:
    app, bot, redis = ingress_app
    FakeBotUser.username = "Home_ai_my_bot"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/telegram/webhook",
            json=group_update(user_id=100500, text="@Home_ai_my_bot купить: творожок"),
        )

    assert response.status_code == 200
    assert redis.jobs == []
    repository = app.state.shopping_repository
    list_id = repository.scope_index[("group", -100123)]
    items = await repository.list_items(list_id)
    assert [item.text for item in items] == ["творожок"]
    final_text = str(bot.sent_messages[0]["text"])
    assert "творожок" in final_text
    assert "@home_ai_my_bot" not in final_text.lower()
    assert bot.chat_actions == []


@pytest.mark.asyncio
async def test_webhook_group_db_allowed_user_mention_enqueues_once(
    ingress_app: tuple[Any, FakeBot, FakeRedis],
) -> None:
    app, bot, redis = ingress_app
    FakeAccessService.allowed_users = {200600}
    FakeAccessService.allowed_groups = {-100123}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/telegram/webhook", json=group_update(user_id=200600))

    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}
    assert redis.jobs == [
        ("process_llm_message", {"chat_id": -100123, "user_id": 200600, "private": False})
    ]
    assert bot.sent_messages == []
    assert bot.chat_actions


@pytest.mark.asyncio
async def test_webhook_group_unauthorized_is_silent_without_job(
    ingress_app: tuple[Any, FakeBot, FakeRedis],
) -> None:
    app, bot, redis = ingress_app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/telegram/webhook", json=group_update(user_id=42))

    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}
    assert redis.jobs == []
    assert bot.sent_messages == []


@pytest.mark.asyncio
async def test_unknown_private_user_whoami_bypasses_access(
    ingress_app: tuple[Any, FakeBot, FakeRedis],
) -> None:
    app, bot, redis = ingress_app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/telegram/webhook",
            json=private_update(user_id=291844566, text="/whoami"),
        )

    assert response.status_code == 200
    assert redis.jobs == []
    assert [message["text"] for message in bot.sent_messages] == [
        "Ваш Telegram user ID: 291844566\n"
        "Тип чата: private\n"
        "Telegram chat ID: 291844566"
    ]


@pytest.mark.asyncio
async def test_unknown_group_user_whoami_bypasses_access(
    ingress_app: tuple[Any, FakeBot, FakeRedis],
) -> None:
    app, bot, redis = ingress_app
    FakeBotUser.username = "Home_ai_my_bot"
    FakeAccessService.allowed_groups = {-5437860232}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/telegram/webhook",
            json=group_update(
                user_id=291844566,
                chat_id=-5437860232,
                chat_type="group",
                text="/whoami@Home_ai_my_bot",
            ),
        )

    assert response.status_code == 200
    assert redis.jobs == []
    assert [message["text"] for message in bot.sent_messages] == [
        "Ваш Telegram user ID: 291844566\n"
        "Тип чата: group\n"
        "Telegram chat ID: -5437860232\n"
        "Пользователь разрешён: нет\n"
        "Группа разрешена: да"
    ]


@pytest.mark.asyncio
async def test_whoami_does_not_enqueue_llm_job(
    ingress_app: tuple[Any, FakeBot, FakeRedis],
) -> None:
    app, _, redis = ingress_app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/telegram/webhook", json=private_update(user_id=42, text="/whoami"))

    assert redis.jobs == []


@pytest.mark.asyncio
async def test_allowed_user_in_allowed_group_mention_enqueues_once(
    ingress_app: tuple[Any, FakeBot, FakeRedis],
    caplog: pytest.LogCaptureFixture,
) -> None:
    app, bot, redis = ingress_app
    FakeBotUser.username = "Home_ai_my_bot"
    FakeAccessService.allowed_users = {291844566}
    FakeAccessService.allowed_groups = {-5437860232}
    caplog.set_level(logging.INFO, logger="app.bot.middlewares.access")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/telegram/webhook",
            json=group_update(
                user_id=291844566,
                chat_id=-5437860232,
                chat_type="group",
                text="@Home_ai_my_bot привет",
            ),
        )

    assert response.status_code == 200
    assert redis.jobs == [
        ("process_llm_message", {"chat_id": -5437860232, "user_id": 291844566, "private": False})
    ]
    assert bot.sent_messages == []
    assert len(bot.chat_actions) == 1
    access_records = [
        record for record in caplog.records if record.message == "telegram_access_decision"
    ]
    assert access_records
    assert access_records[-1].chat_type == "group"
    assert access_records[-1].chat_id == "-***0232"
    assert access_records[-1].user_id == "***4566"
    assert access_records[-1].is_admin is False
    assert access_records[-1].is_user_allowed is True
    assert access_records[-1].has_group_allowlist is True
    assert access_records[-1].is_group_allowed is True
    assert access_records[-1].is_mention_or_reply is True
    assert access_records[-1].decision == "allow"
    assert access_records[-1].reason == "allowed_user"


@pytest.mark.asyncio
async def test_allowed_user_in_allowed_group_reply_enqueues_once(
    ingress_app: tuple[Any, FakeBot, FakeRedis],
) -> None:
    app, bot, redis = ingress_app
    FakeBotUser.username = "Home_ai_my_bot"
    FakeAccessService.allowed_users = {291844566}
    FakeAccessService.allowed_groups = {-5437860232}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/telegram/webhook",
            json=group_update(
                user_id=291844566,
                chat_id=-5437860232,
                chat_type="supergroup",
                text="привет",
                reply_to_user_id=999,
            ),
        )

    assert response.status_code == 200
    assert redis.jobs == [
        ("process_llm_message", {"chat_id": -5437860232, "user_id": 291844566, "private": False})
    ]
    assert bot.sent_messages == []
    assert len(bot.chat_actions) == 1


@pytest.mark.asyncio
async def test_allowed_user_without_mention_is_ignored(
    ingress_app: tuple[Any, FakeBot, FakeRedis],
) -> None:
    app, bot, redis = ingress_app
    FakeAccessService.allowed_users = {291844566}
    FakeAccessService.allowed_groups = {-5437860232}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/telegram/webhook",
            json=group_update(user_id=291844566, chat_id=-5437860232, text="привет"),
        )

    assert response.status_code == 200
    assert redis.jobs == []
    assert bot.sent_messages == []
    assert bot.chat_actions == []


@pytest.mark.asyncio
async def test_group_buy_colon_without_mention_is_ignored(
    ingress_app: tuple[Any, FakeBot, FakeRedis],
) -> None:
    app, bot, redis = ingress_app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/telegram/webhook",
            json=group_update(user_id=100500, text="купить: хлеб"),
        )

    assert response.status_code == 200
    assert redis.jobs == []
    assert ("group", -100123) not in app.state.shopping_repository.scope_index
    assert bot.sent_messages == []
    assert bot.chat_actions == []


@pytest.mark.asyncio
async def test_unknown_user_in_allowed_group_is_silent(
    ingress_app: tuple[Any, FakeBot, FakeRedis],
) -> None:
    app, bot, redis = ingress_app
    FakeBotUser.username = "Home_ai_my_bot"
    FakeAccessService.allowed_groups = {-5437860232}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/telegram/webhook",
            json=group_update(
                user_id=123456789,
                chat_id=-5437860232,
                text="@Home_ai_my_bot привет",
            ),
        )

    assert response.status_code == 200
    assert redis.jobs == []
    assert bot.sent_messages == []


@pytest.mark.asyncio
async def test_allowed_user_in_disallowed_group_is_silent(
    ingress_app: tuple[Any, FakeBot, FakeRedis],
) -> None:
    app, bot, redis = ingress_app
    FakeBotUser.username = "Home_ai_my_bot"
    FakeAccessService.allowed_users = {291844566}
    FakeAccessService.allowed_groups = {-100999}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/telegram/webhook",
            json=group_update(
                user_id=291844566,
                chat_id=-5437860232,
                text="@Home_ai_my_bot привет",
            ),
        )

    assert response.status_code == 200
    assert redis.jobs == []
    assert bot.sent_messages == []


@pytest.mark.asyncio
async def test_group_access_uses_from_user_id(
    ingress_app: tuple[Any, FakeBot, FakeRedis],
) -> None:
    app, bot, redis = ingress_app
    FakeBotUser.username = "Home_ai_my_bot"
    FakeAccessService.allowed_users = {-5437860232}
    FakeAccessService.allowed_groups = {-5437860232}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/telegram/webhook",
            json=group_update(
                user_id=291844566,
                chat_id=-5437860232,
                text="@Home_ai_my_bot привет",
            ),
        )

    assert response.status_code == 200
    assert redis.jobs == []
    assert bot.sent_messages == []


@pytest.mark.asyncio
async def test_group_access_uses_signed_chat_id(
    ingress_app: tuple[Any, FakeBot, FakeRedis],
) -> None:
    app, bot, redis = ingress_app
    FakeBotUser.username = "Home_ai_my_bot"
    FakeAccessService.allowed_users = {291844566}
    FakeAccessService.allowed_groups = {5437860232}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/telegram/webhook",
            json=group_update(
                user_id=291844566,
                chat_id=-5437860232,
                text="@Home_ai_my_bot привет",
            ),
        )

    assert response.status_code == 200
    assert redis.jobs == []
    assert bot.sent_messages == []


@pytest.mark.asyncio
async def test_access_db_error_denies_safely(
    ingress_app: tuple[Any, FakeBot, FakeRedis],
) -> None:
    app, bot, redis = ingress_app
    FakeBotUser.username = "Home_ai_my_bot"
    FakeAccessService.raise_error = True

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/telegram/webhook",
            json=group_update(
                user_id=291844566,
                chat_id=-5437860232,
                text="@Home_ai_my_bot привет",
            ),
        )

    assert response.status_code == 200
    assert redis.jobs == []
    assert bot.sent_messages == []
