from typing import Any

import pytest

from app.bot.routers.groups import handle_group_message, should_answer_group_message
from app.core.config import Settings
from app.db.models import MessageRole
from app.services.memory_service import InMemoryMessageRepository, MemoryService


class FakeChat:
    type = "group"
    id = -100123


class FakeUser:
    id = 456


class FakeBotUser:
    id = 999


class FakeBot:
    def __init__(self) -> None:
        self.actions: list[tuple[int, Any]] = []

    async def get_me(self) -> FakeBotUser:
        return FakeBotUser()

    async def send_chat_action(self, *, chat_id: int, action: Any) -> None:
        self.actions.append((chat_id, action))


class FakeRedis:
    def __init__(self) -> None:
        self.jobs: list[tuple[str, dict[str, Any]]] = []

    async def enqueue_job(self, name: str, payload: dict[str, Any]) -> None:
        self.jobs.append((name, payload))


class FakeMessage:
    def __init__(self, text: str, *, reply_to_bot: bool = False) -> None:
        self.chat = FakeChat()
        self.from_user = FakeUser()
        self.text = text
        self.message_id = 77
        self.answers: list[str] = []
        self.reply_to_message = None
        if reply_to_bot:
            self.reply_to_message = type(
                "Reply",
                (),
                {"from_user": FakeBotUser()},
            )()

    async def answer(self, text: str, **kwargs: Any) -> None:
        self.answers.append(text)


def test_group_handler_ignores_unrelated_messages() -> None:
    assert should_answer_group_message("привет", None, "jarvis_bot") is False


def test_group_handler_responds_to_mention() -> None:
    assert should_answer_group_message("привет @jarvis_bot", None, "jarvis_bot") is True


def test_group_handler_responds_to_reply_to_bot() -> None:
    assert should_answer_group_message("привет", 100, "jarvis_bot", bot_user_id=100) is True


def test_group_assistant_enabled_default_does_not_need_business_mode() -> None:
    settings = Settings(group_assistant_enabled=True, business_mode_enabled=False)

    assert settings.group_assistant_enabled is True
    assert settings.business_mode_enabled is False


@pytest.mark.asyncio
async def test_group_mention_records_message_and_enqueues_worker_job() -> None:
    repository = InMemoryMessageRepository()
    memory = MemoryService(repository, max_messages=10)
    redis = FakeRedis()
    message = FakeMessage("@jarvis_bot кратко объясни DNS")

    await handle_group_message(
        message,  # type: ignore[arg-type]
        settings=Settings(telegram_bot_username="jarvis_bot"),
        bot=FakeBot(),
        memory_service=memory,
        redis=redis,
    )

    assert message.answers == ["Принял. Готовлю групповой ответ."]
    assert repository.messages[0].role == MessageRole.USER
    assert repository.messages[0].content == "@jarvis_bot кратко объясни DNS"
    assert redis.jobs == [
        (
            "process_llm_message",
            {"chat_id": message.chat.id, "user_id": message.from_user.id, "private": False},
        )
    ]


@pytest.mark.asyncio
async def test_group_plain_message_without_mention_is_not_saved_or_queued() -> None:
    repository = InMemoryMessageRepository()
    memory = MemoryService(repository, max_messages=10)
    redis = FakeRedis()
    message = FakeMessage("это сообщение бот должен игнорировать")

    await handle_group_message(
        message,  # type: ignore[arg-type]
        settings=Settings(telegram_bot_username="jarvis_bot"),
        bot=FakeBot(),
        memory_service=memory,
        redis=redis,
    )

    assert message.answers == []
    assert repository.messages == []
    assert redis.jobs == []
