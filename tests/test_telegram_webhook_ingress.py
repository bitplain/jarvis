import logging
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import routes_telegram
from app.bot.middlewares import access
from app.bot.routers import commands, groups, private
from app.core.config import Settings
from app.core.config import get_settings as app_get_settings
from app.db.models import MessageRole
from app.main import create_app
from app.services.runtime_settings_service import (
    DEFAULT_PROMPTS,
    PromptProfile,
    PromptProfileScope,
    PromptSetting,
    PromptSource,
)
from app.services.telegram_access_service import AccessEntry


class FakeTelegramMessage:
    message_id = 9001


class FakeBotUser:
    id = 999
    username = "jarvis_bot"


class FakeBot:
    id = 999

    def __init__(self) -> None:
        self.sent_messages: list[dict[str, object]] = []
        self.chat_actions: list[dict[str, object]] = []

    async def __call__(self, method: object, **kwargs: object) -> FakeTelegramMessage:
        del kwargs
        method_name = method.__class__.__name__
        if method_name == "SendMessage":
            self.sent_messages.append(
                {
                    "chat_id": method.chat_id,  # type: ignore[attr-defined]
                    "text": method.text,  # type: ignore[attr-defined]
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

    async def enqueue_job(self, name: str, payload: dict[str, Any]) -> None:
        self.jobs.append((name, payload))


class BrokenRedisConnect(RuntimeError):
    pass


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


def private_update(*, user_id: int, text: str = "тест") -> dict[str, object]:
    return {
        "update_id": 101,
        "message": {
            "message_id": 10,
            "date": 1_700_000_000,
            "chat": {"id": user_id, "type": "private", "first_name": "User"},
            "from": {"id": user_id, "is_bot": False, "first_name": "User"},
            "text": text,
        },
    }


def callback_update(data: str, *, user_id: int = 100500) -> dict[str, object]:
    return {
        "update_id": 103,
        "callback_query": {
            "id": "callback-1",
            "from": {"id": user_id, "is_bot": False, "first_name": "User"},
            "message": {
                "message_id": 20,
                "date": 1_700_000_000,
                "chat": {"id": user_id, "type": "private", "first_name": "User"},
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
) -> dict[str, object]:
    message: dict[str, object] = {
        "message_id": 11,
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
        "update_id": 102,
        "message": message,
    }


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

    async def fake_get_session() -> AsyncIterator[object]:
        yield object()

    app = create_app(settings=settings)
    app.state.bot = fake_bot
    app.state.redis_pool = fake_redis
    app.dependency_overrides[app_get_settings] = lambda: settings
    app.dependency_overrides[routes_telegram.get_session] = fake_get_session
    monkeypatch.setattr(private, "MessageRepository", FakeMessageRepository)
    monkeypatch.setattr(groups, "MessageRepository", FakeMessageRepository)
    monkeypatch.setattr(access, "TelegramAccessRepository", lambda session: object())
    monkeypatch.setattr(access, "TelegramAccessService", FakeAccessService)
    monkeypatch.setattr(commands, "TelegramAccessRepository", lambda session: object())
    monkeypatch.setattr(commands, "TelegramAccessService", FakeAccessService)
    monkeypatch.setattr(commands, "RuntimeSettingsService", FakeRuntimeSettingsService)
    FakeAccessService.allowed_users = set()
    FakeAccessService.allowed_groups = set()
    FakeAccessService.raise_error = False
    FakeRuntimeSettingsService.prompts = {}
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
    assert [message["text"] for message in bot.sent_messages] == ["Принял. Готовлю ответ."]


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
    assert [message["text"] for message in bot.sent_messages] == ["Принял. Готовлю ответ."]


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
    assert [message["text"] for message in bot.sent_messages] == ["Принял. Готовлю ответ."]


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
    assert [message["text"] for message in bot.sent_messages] == ["Принял. Готовлю ответ."]


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
    assert [message["text"] for message in bot.sent_messages] == ["Принял. Готовлю ответ."]


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
