from typing import Any

import pytest

from app.bot.routers.groups import handle_group_message
from app.bot.routers.private import handle_private_text
from app.core.config import Settings
from app.db.models import MessageRole
from app.services.memory_service import InMemoryMessageRepository, MemoryService


class FakePrivateChat:
    id = 100500
    type = "private"


class FakeGroupChat:
    id = -100123
    type = "group"


class FakeUser:
    id = 456


class FakeBotUser:
    id = 999
    username = "jarvis_bot"


class FakeBot:
    async def get_me(self) -> FakeBotUser:
        return FakeBotUser()

    async def send_chat_action(self, *, chat_id: int, action: Any) -> None:
        del chat_id, action


class FakeRedis:
    def __init__(self) -> None:
        self.jobs: list[tuple[str, dict[str, Any], dict[str, Any]]] = []

    async def enqueue_job(self, name: str, payload: dict[str, Any], **kwargs: Any) -> None:
        self.jobs.append((name, payload, kwargs))


class FakePrivateMessage:
    def __init__(self, text: str) -> None:
        self.chat = FakePrivateChat()
        self.from_user = FakeUser()
        self.text = text
        self.caption = None
        self.message_id = 77
        self.answers: list[str] = []

    async def answer(self, text: str, **kwargs: Any) -> None:
        del kwargs
        self.answers.append(text)


class FakeGroupMessage(FakePrivateMessage):
    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.chat = FakeGroupChat()
        self.reply_to_message = None


@pytest.mark.asyncio
async def test_private_explicit_search_enqueues_web_search_payload() -> None:
    repository = InMemoryMessageRepository()
    memory = MemoryService(repository, max_messages=10)
    redis = FakeRedis()
    message = FakePrivateMessage("найди последние обновления Railway")

    await handle_private_text(
        message,  # type: ignore[arg-type]
        settings=Settings(),
        memory_service=memory,
        redis=redis,
    )

    assert message.answers == ["Думаю"]
    assert repository.messages[0].role == MessageRole.USER
    assert redis.jobs[0][0] == "process_llm_message"
    assert redis.jobs[0][1]["web_search"]["query"] == "последние обновления Railway"
    assert redis.jobs[0][1]["private"] is True


@pytest.mark.asyncio
async def test_private_normal_message_keeps_generic_llm_path() -> None:
    repository = InMemoryMessageRepository()
    memory = MemoryService(repository, max_messages=10)
    redis = FakeRedis()
    message = FakePrivateMessage("Привет")

    await handle_private_text(
        message,  # type: ignore[arg-type]
        settings=Settings(),
        memory_service=memory,
        redis=redis,
    )

    assert "web_search" not in redis.jobs[0][1]


@pytest.mark.asyncio
async def test_group_mention_search_enqueues_web_search_payload() -> None:
    repository = InMemoryMessageRepository()
    memory = MemoryService(repository, max_messages=10)
    redis = FakeRedis()
    message = FakeGroupMessage("@jarvis_bot найди последние обновления Railway")

    await handle_group_message(
        message,  # type: ignore[arg-type]
        settings=Settings(telegram_bot_username="jarvis_bot"),
        bot=FakeBot(),
        memory_service=memory,
        redis=redis,
    )

    assert redis.jobs[0][1]["web_search"]["query"] == "последние обновления Railway"
    assert redis.jobs[0][1]["private"] is False
