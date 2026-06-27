import time
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
        self.values: dict[str, str] = {}
        self.deleted: list[str] = []

    async def enqueue_job(self, name: str, payload: dict[str, Any], **kwargs: Any) -> None:
        self.jobs.append((name, payload, kwargs))

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, *, ex: int) -> bool:
        del ex
        self.values[key] = value
        return True

    async def delete(self, key: str) -> int:
        self.deleted.append(key)
        self.values.pop(key, None)
        return 1


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


class BrokenRedis(FakeRedis):
    async def get(self, key: str) -> str | None:
        del key
        raise RuntimeError("redis unavailable")

    async def set(self, key: str, value: str, *, ex: int) -> bool:
        del key, value, ex
        raise RuntimeError("redis unavailable")

    async def delete(self, key: str) -> int:
        del key
        raise RuntimeError("redis unavailable")


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
async def test_private_weather_phrase_enqueues_web_search_payload() -> None:
    repository = InMemoryMessageRepository()
    memory = MemoryService(repository, max_messages=10)
    redis = FakeRedis()
    message = FakePrivateMessage("Покажи погоду в Москве")

    await handle_private_text(
        message,  # type: ignore[arg-type]
        settings=Settings(),
        memory_service=memory,
        redis=redis,
    )

    assert redis.jobs[0][1]["web_search"]["query"] == "погода в Москве сегодня"


@pytest.mark.asyncio
async def test_private_vague_weather_creates_pending_clarification() -> None:
    repository = InMemoryMessageRepository()
    memory = MemoryService(repository, max_messages=10)
    redis = FakeRedis()
    message = FakePrivateMessage("Найди в интернете погода на сегодня")

    await handle_private_text(
        message,  # type: ignore[arg-type]
        settings=Settings(),
        memory_service=memory,
        redis=redis,
    )

    assert redis.jobs == []
    assert message.answers == ["Укажите город или страну для прогноза погоды."]
    assert redis.values
    assert "web_search:clarification:private:100500:456" in redis.values


@pytest.mark.asyncio
async def test_private_weather_followup_city_triggers_search() -> None:
    repository = InMemoryMessageRepository()
    memory = MemoryService(repository, max_messages=10)
    redis = FakeRedis()
    created_at = time.time()
    redis.values["web_search:clarification:private:100500:456"] = (
        '{"kind":"web_search_clarification","intent_type":"weather",'
        f'"original_query":"погода на сегодня","created_at":{created_at}}}'
    )
    message = FakePrivateMessage("Москва")

    await handle_private_text(
        message,  # type: ignore[arg-type]
        settings=Settings(),
        memory_service=memory,
        redis=redis,
    )

    assert redis.jobs[0][1]["web_search"]["query"] == "погода Москва сегодня"
    assert redis.deleted == ["web_search:clarification:private:100500:456"]


@pytest.mark.asyncio
async def test_private_weather_followup_explicit_phrase_triggers_search() -> None:
    repository = InMemoryMessageRepository()
    memory = MemoryService(repository, max_messages=10)
    redis = FakeRedis()
    created_at = time.time()
    redis.values["web_search:clarification:private:100500:456"] = (
        '{"kind":"web_search_clarification","intent_type":"weather",'
        f'"original_query":"погода на сегодня","created_at":{created_at}}}'
    )
    message = FakePrivateMessage("Покажи погоду в Москве")

    await handle_private_text(
        message,  # type: ignore[arg-type]
        settings=Settings(),
        memory_service=memory,
        redis=redis,
    )

    assert redis.jobs[0][1]["web_search"]["query"] == "погода в Москве сегодня"
    assert redis.deleted == ["web_search:clarification:private:100500:456"]


@pytest.mark.asyncio
async def test_private_cancel_clears_web_search_clarification() -> None:
    repository = InMemoryMessageRepository()
    memory = MemoryService(repository, max_messages=10)
    redis = FakeRedis()
    created_at = time.time()
    redis.values["web_search:clarification:private:100500:456"] = (
        '{"kind":"web_search_clarification","intent_type":"weather",'
        f'"original_query":"погода на сегодня","created_at":{created_at}}}'
    )
    message = FakePrivateMessage("/cancel")

    await handle_private_text(
        message,  # type: ignore[arg-type]
        settings=Settings(),
        memory_service=memory,
        redis=redis,
    )

    assert redis.deleted == ["web_search:clarification:private:100500:456"]
    assert redis.jobs == []


@pytest.mark.asyncio
async def test_private_expired_clarification_keeps_normal_llm_path() -> None:
    repository = InMemoryMessageRepository()
    memory = MemoryService(repository, max_messages=10)
    redis = FakeRedis()
    redis.values["web_search:clarification:private:100500:456"] = (
        '{"kind":"web_search_clarification","intent_type":"weather",'
        '"original_query":"погода на сегодня","created_at":1}'
    )
    message = FakePrivateMessage("Москва")

    await handle_private_text(
        message,  # type: ignore[arg-type]
        settings=Settings(),
        memory_service=memory,
        redis=redis,
    )

    assert "web_search" not in redis.jobs[0][1]


@pytest.mark.asyncio
async def test_private_redis_unavailable_does_not_break_normal_message() -> None:
    repository = InMemoryMessageRepository()
    memory = MemoryService(repository, max_messages=10)
    redis = BrokenRedis()
    message = FakePrivateMessage("Привет")

    await handle_private_text(
        message,  # type: ignore[arg-type]
        settings=Settings(),
        memory_service=memory,
        redis=redis,
    )

    assert redis.jobs[0][0] == "process_llm_message"
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


@pytest.mark.asyncio
async def test_group_mention_weather_search_enqueues_web_search_payload() -> None:
    repository = InMemoryMessageRepository()
    memory = MemoryService(repository, max_messages=10)
    redis = FakeRedis()
    message = FakeGroupMessage("@jarvis_bot покажи погоду в Москве")

    await handle_group_message(
        message,  # type: ignore[arg-type]
        settings=Settings(telegram_bot_username="jarvis_bot"),
        bot=FakeBot(),
        memory_service=memory,
        redis=redis,
    )

    assert redis.jobs[0][1]["web_search"]["query"] == "погода в Москве сегодня"
    assert redis.jobs[0][1]["private"] is False


@pytest.mark.asyncio
async def test_group_plain_weather_does_not_search() -> None:
    repository = InMemoryMessageRepository()
    memory = MemoryService(repository, max_messages=10)
    redis = FakeRedis()
    message = FakeGroupMessage("Покажи погоду в Москве")

    await handle_group_message(
        message,  # type: ignore[arg-type]
        settings=Settings(telegram_bot_username="jarvis_bot"),
        bot=FakeBot(),
        memory_service=memory,
        redis=redis,
    )

    assert redis.jobs == []
