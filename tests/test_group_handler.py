from typing import Any

import pytest

from app.bot.routers.groups import (
    classify_group_message,
    handle_group_message,
    should_answer_group_message,
)
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
    username = "jarvis_bot"


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
    def __init__(
        self,
        text: str,
        *,
        reply_to_bot: bool = False,
        reply_to_user_id: int | None = None,
        chat_type: str = "group",
    ) -> None:
        self.chat = FakeChat()
        self.chat.type = chat_type
        self.from_user = FakeUser()
        self.text = text
        self.message_id = 77
        self.answers: list[str] = []
        self.reply_to_message = None
        if reply_to_bot:
            reply_to_user_id = FakeBotUser.id
        if reply_to_user_id is not None:
            self.reply_to_message = type(
                "Reply",
                (),
                {"from_user": type("ReplyUser", (), {"id": reply_to_user_id})()},
            )()

    async def answer(self, text: str, **kwargs: Any) -> None:
        self.answers.append(text)


def test_group_handler_ignores_unrelated_messages() -> None:
    assert should_answer_group_message("привет", None, "jarvis_bot") is False


def test_group_handler_responds_to_mention() -> None:
    assert should_answer_group_message("привет @jarvis_bot", None, "jarvis_bot") is True


def test_group_handler_responds_to_reply_to_bot() -> None:
    assert should_answer_group_message("привет", 100, "jarvis_bot", bot_user_id=100) is True


def test_group_handler_ignores_other_bot_mention() -> None:
    assert should_answer_group_message("@other_bot привет", None, "jarvis_bot") is False


def test_group_handler_responds_to_command_mention_for_current_bot() -> None:
    decision = classify_group_message(
        "/summary@Jarvis_Bot кратко перескажи DNS",
        None,
        "jarvis_bot",
        bot_user_id=100,
    )

    assert decision.text_classification == "command_mention"
    assert decision.matched_bot_username is True
    assert decision.should_process is True


def test_group_handler_ignores_command_mention_for_other_bot() -> None:
    decision = classify_group_message(
        "/summary@Other_Bot кратко перескажи DNS",
        None,
        "jarvis_bot",
        bot_user_id=100,
    )

    assert decision.text_classification == "command_mention"
    assert decision.matched_bot_username is False
    assert decision.should_process is False


def test_group_handler_detects_empty_text_mention() -> None:
    decision = classify_group_message("@Jarvis_Bot", None, "jarvis_bot", bot_user_id=100)

    assert decision.text_classification == "empty_mention"
    assert decision.matched_bot_username is True
    assert decision.should_process is False
    assert decision.needs_query_after_mention is True


def test_group_handler_reply_to_non_bot_without_mention_is_ignored() -> None:
    decision = classify_group_message("кратко поясни это", 555, "jarvis_bot", bot_user_id=100)

    assert decision.text_classification == "plain"
    assert decision.should_process is False


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
async def test_group_mention_uses_runtime_bot_username_when_env_username_is_stale() -> None:
    repository = InMemoryMessageRepository()
    memory = MemoryService(repository, max_messages=10)
    redis = FakeRedis()
    message = FakeMessage("@jarvis_bot кратко объясни DNS")

    await handle_group_message(
        message,  # type: ignore[arg-type]
        settings=Settings(telegram_bot_username="59144850"),
        bot=FakeBot(),
        memory_service=memory,
        redis=redis,
    )

    assert message.answers == ["Принял. Готовлю групповой ответ."]
    assert repository.messages[0].content == "@jarvis_bot кратко объясни DNS"
    assert redis.jobs[0][1]["private"] is False


@pytest.mark.asyncio
async def test_group_reply_to_bot_records_message_and_enqueues_worker_job() -> None:
    repository = InMemoryMessageRepository()
    memory = MemoryService(repository, max_messages=10)
    redis = FakeRedis()
    message = FakeMessage("кратко поясни это", reply_to_bot=True)

    await handle_group_message(
        message,  # type: ignore[arg-type]
        settings=Settings(telegram_bot_username="jarvis_bot"),
        bot=FakeBot(),
        memory_service=memory,
        redis=redis,
    )

    assert message.answers == ["Принял. Готовлю групповой ответ."]
    assert repository.messages[0].content == "кратко поясни это"
    assert redis.jobs[0][1]["private"] is False


@pytest.mark.asyncio
async def test_group_empty_mention_returns_helpful_answer_without_worker_job() -> None:
    repository = InMemoryMessageRepository()
    memory = MemoryService(repository, max_messages=10)
    redis = FakeRedis()
    message = FakeMessage("@jarvis_bot")

    await handle_group_message(
        message,  # type: ignore[arg-type]
        settings=Settings(telegram_bot_username="jarvis_bot"),
        bot=FakeBot(),
        memory_service=memory,
        redis=redis,
    )

    assert message.answers == ["Напиши запрос после упоминания бота."]
    assert repository.messages == []
    assert redis.jobs == []


@pytest.mark.asyncio
async def test_group_handler_does_not_process_private_message() -> None:
    repository = InMemoryMessageRepository()
    memory = MemoryService(repository, max_messages=10)
    redis = FakeRedis()
    message = FakeMessage("@jarvis_bot кратко объясни DNS", chat_type="private")

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
