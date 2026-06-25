from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import routes_telegram
from app.bot.routers import commands, private
from app.core.config import Settings
from app.core.config import get_settings as app_get_settings
from app.main import create_app


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
        elif method_name == "EditMessageText":
            self.edited_messages.append(
                {
                    "chat_id": method.chat_id,  # type: ignore[attr-defined]
                    "text": method.text,  # type: ignore[attr-defined]
                }
            )
        elif method_name == "AnswerCallbackQuery":
            self.callback_answers.append(
                {
                    "callback_query_id": method.callback_query_id,  # type: ignore[attr-defined]
                    "text": method.text,  # type: ignore[attr-defined]
                }
            )
        return FakeTelegramMessage()

    async def get_me(self) -> FakeBotUser:
        return FakeBotUser()


class FakeRedis:
    def __init__(self) -> None:
        self.jobs: list[tuple[str, dict[str, Any]]] = []

    async def enqueue_job(self, name: str, payload: dict[str, Any]) -> None:
        self.jobs.append((name, payload))


class FakeMessageRepository:
    def __init__(self, session: object) -> None:
        del session

    async def add_message(self, **kwargs: object) -> None:
        del kwargs

    async def recent_messages(self, **kwargs: object) -> list[object]:
        del kwargs
        return []

    async def clear_chat(self, **kwargs: object) -> None:
        del kwargs


class FakeTelegramAccessService:
    added_users: list[tuple[int, str | None, int | None]] = []
    removed_users: list[int] = []
    added_groups: list[tuple[int, str | None, int | None]] = []
    removed_groups: list[int] = []
    users: list[commands.AccessEntry] = []
    groups: list[commands.AccessEntry] = []

    def __init__(self, repository: object, *, admin_ids: set[int]) -> None:
        del repository
        self.admin_ids = admin_ids

    def is_admin_user(self, user_id: int | None) -> bool:
        return user_id is not None and user_id in self.admin_ids

    async def list_allowed_users(self) -> list[commands.AccessEntry]:
        return self.users

    async def list_allowed_groups(self) -> list[commands.AccessEntry]:
        return self.groups

    async def add_allowed_user(
        self,
        user_id: int,
        label: str | None,
        *,
        created_by: int | None,
    ) -> None:
        self.added_users.append((user_id, label, created_by))
        self.users.append(commands.AccessEntry("user", user_id, label, created_by))

    async def remove_allowed_user(self, user_id: int) -> bool:
        self.removed_users.append(user_id)
        before = len(self.users)
        self.users = [entry for entry in self.users if entry.telegram_id != user_id]
        return len(self.users) != before

    async def add_allowed_group(
        self,
        chat_id: int,
        label: str | None,
        *,
        created_by: int | None,
    ) -> None:
        self.added_groups.append((chat_id, label, created_by))
        self.groups.append(commands.AccessEntry("group", chat_id, label, created_by))

    async def remove_allowed_group(self, chat_id: int) -> bool:
        self.removed_groups.append(chat_id)
        before = len(self.groups)
        self.groups = [entry for entry in self.groups if entry.telegram_id != chat_id]
        return len(self.groups) != before


def callback_update(data: str, *, user_id: int = 100500) -> dict[str, object]:
    return {
        "update_id": 900,
        "callback_query": {
            "id": "callback-1",
            "from": {"id": user_id, "is_bot": False, "first_name": "Admin"},
            "message": {
                "message_id": 50,
                "date": 1_700_000_000,
                "chat": {"id": user_id, "type": "private", "first_name": "Admin"},
                "from": {"id": 999, "is_bot": True, "first_name": "Jarvis"},
                "text": "Разрешённые пользователи",
            },
            "chat_instance": "chat-instance",
            "data": data,
        },
    }


def private_update(text: str, *, user_id: int = 100500, update_id: int = 901) -> dict[str, object]:
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "date": 1_700_000_000,
            "chat": {"id": user_id, "type": "private", "first_name": "Admin"},
            "from": {"id": user_id, "is_bot": False, "first_name": "Admin"},
            "text": text,
        },
    }


@pytest.fixture
def fsm_app(monkeypatch: pytest.MonkeyPatch) -> tuple[Any, FakeBot, FakeRedis]:
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

    monkeypatch.setattr(commands, "TelegramAccessRepository", lambda session: object())
    monkeypatch.setattr(commands, "TelegramAccessService", FakeTelegramAccessService)
    monkeypatch.setattr(private, "MessageRepository", FakeMessageRepository)
    FakeTelegramAccessService.added_users = []
    FakeTelegramAccessService.removed_users = []
    FakeTelegramAccessService.added_groups = []
    FakeTelegramAccessService.removed_groups = []
    FakeTelegramAccessService.users = []
    FakeTelegramAccessService.groups = []
    return app, fake_bot, fake_redis


async def post_update(app: Any, payload: dict[str, object]) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/telegram/webhook", json=payload)
    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}


@pytest.mark.asyncio
async def test_add_user_state_intercepts_text_before_private_llm(
    fsm_app: tuple[Any, FakeBot, FakeRedis],
) -> None:
    app, bot, redis = fsm_app

    await post_update(app, callback_update("settings:access:user:add"))
    await post_update(app, private_update("5117224471 Александр"))

    assert FakeTelegramAccessService.added_users == [(5117224471, "Александр", 100500)]
    assert redis.jobs == []
    assert "Готовлю ответ" not in "\n".join(str(item["text"]) for item in bot.sent_messages)


@pytest.mark.asyncio
async def test_add_user_state_supports_multiple_ids_space_separated(
    fsm_app: tuple[Any, FakeBot, FakeRedis],
) -> None:
    app, bot, redis = fsm_app

    await post_update(app, callback_update("settings:access:user:add"))
    await post_update(app, private_update("5117224471 291844566"))

    assert FakeTelegramAccessService.added_users == [
        (5117224471, None, 100500),
        (291844566, None, 100500),
    ]
    assert redis.jobs == []
    assert "Добавлены пользователи" in str(bot.sent_messages[-1]["text"])


@pytest.mark.asyncio
async def test_add_user_state_supports_multiple_ids_newline_separated(
    fsm_app: tuple[Any, FakeBot, FakeRedis],
) -> None:
    app, _bot, redis = fsm_app

    await post_update(app, callback_update("settings:access:user:add"))
    await post_update(app, private_update("5117224471\n291844566"))

    assert FakeTelegramAccessService.added_users == [
        (5117224471, None, 100500),
        (291844566, None, 100500),
    ]
    assert redis.jobs == []


@pytest.mark.asyncio
async def test_add_group_state_intercepts_text_before_private_llm(
    fsm_app: tuple[Any, FakeBot, FakeRedis],
) -> None:
    app, bot, redis = fsm_app

    await post_update(app, callback_update("settings:access:group:add"))
    await post_update(app, private_update("-5437860232 Домашний чат"))

    assert FakeTelegramAccessService.added_groups == [(-5437860232, "Домашний чат", 100500)]
    assert redis.jobs == []
    assert "Готовлю ответ" not in "\n".join(str(item["text"]) for item in bot.sent_messages)


@pytest.mark.asyncio
async def test_remove_user_state_intercepts_text(
    fsm_app: tuple[Any, FakeBot, FakeRedis],
) -> None:
    app, _bot, redis = fsm_app

    await post_update(app, callback_update("settings:access:user:remove"))
    await post_update(app, private_update("5117224471"))

    assert FakeTelegramAccessService.removed_users == [5117224471]
    assert redis.jobs == []


@pytest.mark.asyncio
async def test_remove_group_state_intercepts_text(
    fsm_app: tuple[Any, FakeBot, FakeRedis],
) -> None:
    app, _bot, redis = fsm_app

    await post_update(app, callback_update("settings:access:group:remove"))
    await post_update(app, private_update("-5437860232"))

    assert FakeTelegramAccessService.removed_groups == [-5437860232]
    assert redis.jobs == []


@pytest.mark.asyncio
async def test_cancel_clears_access_fsm_state(
    fsm_app: tuple[Any, FakeBot, FakeRedis],
) -> None:
    app, bot, redis = fsm_app

    await post_update(app, callback_update("settings:access:user:add"))
    await post_update(app, private_update("/cancel"))
    await post_update(app, private_update("обычный вопрос", update_id=902))

    assert FakeTelegramAccessService.added_users == []
    assert redis.jobs == [
        ("process_llm_message", {"chat_id": 100500, "user_id": 100500, "private": True})
    ]
    assert [item["text"] for item in bot.sent_messages] == [
        "Ввод отменён.",
        "Принял. Готовлю ответ.",
    ]


@pytest.mark.asyncio
async def test_invalid_access_fsm_input_does_not_enqueue_llm(
    fsm_app: tuple[Any, FakeBot, FakeRedis],
) -> None:
    app, bot, redis = fsm_app

    await post_update(app, callback_update("settings:access:user:add"))
    await post_update(app, private_update("это не ID"))

    assert FakeTelegramAccessService.added_users == []
    assert redis.jobs == []
    assert "Не понял ID" in str(bot.sent_messages[-1]["text"])
