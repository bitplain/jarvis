from typing import Any

import pytest

from app.bot.routers import commands
from app.core.config import Settings
from app.db.models import MessageRole
from app.llm.types import LLMMessage, LLMResponse
from app.services.memory_service import MemoryMessage


class FakeChat:
    id = 123


class FakeMessage:
    def __init__(self, text: str) -> None:
        self.chat = FakeChat()
        self.text = text
        self.answers: list[str] = []

    async def answer(self, text: str, **kwargs: Any) -> None:
        self.answers.append(text)


class FakeBotUser:
    username = "Home_ai_my_bot"


class FakeBot:
    async def get_me(self) -> FakeBotUser:
        return FakeBotUser()


class FakeRepository:
    async def recent_messages(
        self,
        *,
        chat_id: int,
        limit: int,
    ) -> list[MemoryMessage]:
        del chat_id, limit
        return [
            MemoryMessage(
                chat_id=123,
                user_id=456,
                role=MessageRole.USER,
                content="старый контекст из памяти",
            )
        ]


class CapturingProvider:
    name = "test"

    def __init__(self) -> None:
        self.rendered_prompt = ""

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        del max_tokens
        self.rendered_prompt = "\n".join(message.content for message in messages)
        return LLMResponse(content="готово", provider=self.name, model="test-model")

    async def stream(self, messages: list[LLMMessage]):
        del messages
        yield "unused"

    async def list_models(self) -> list[str]:
        return ["test-model"]


@pytest.mark.asyncio
async def test_translate_command_uses_inline_argument_before_chat_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = CapturingProvider()
    monkeypatch.setattr(commands, "MessageRepository", lambda session: FakeRepository())
    message = FakeMessage("/translate Переведи на английский: сервер успешно перезапущен")

    await commands.cmd_translate(
        message,  # type: ignore[arg-type]
        settings=Settings(),
        db_session=object(),
        llm_provider=provider,
    )

    assert "Переведи на английский: сервер успешно перезапущен" in provider.rendered_prompt
    assert "старый контекст из памяти" not in provider.rendered_prompt
    assert message.answers == ["готово"]


@pytest.mark.asyncio
async def test_factcheck_command_with_bot_username_uses_inline_argument(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = CapturingProvider()
    monkeypatch.setattr(commands, "MessageRepository", lambda session: FakeRepository())
    message = FakeMessage(
        "/factcheck@Home_ai_my_bot Проверь факт: PostgreSQL - это реляционная СУБД"
    )

    await commands.cmd_factcheck(
        message,  # type: ignore[arg-type]
        settings=Settings(telegram_bot_username="Home_ai_my_bot"),
        db_session=object(),
        llm_provider=provider,
    )

    assert "Проверь факт: PostgreSQL - это реляционная СУБД" in provider.rendered_prompt
    assert "старый контекст из памяти" not in provider.rendered_prompt
    assert message.answers == ["готово"]


@pytest.mark.asyncio
async def test_summary_command_with_bot_username_uses_inline_argument(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = CapturingProvider()
    monkeypatch.setattr(commands, "MessageRepository", lambda session: FakeRepository())
    message = FakeMessage("/summary@Home_ai_my_bot кратко перескажи, зачем нужен DNS")

    await commands.cmd_summary(
        message,  # type: ignore[arg-type]
        settings=Settings(telegram_bot_username="Home_ai_my_bot"),
        db_session=object(),
        llm_provider=provider,
    )

    assert "кратко перескажи, зачем нужен DNS" in provider.rendered_prompt
    assert "старый контекст из памяти" not in provider.rendered_prompt
    assert message.answers == ["готово"]


@pytest.mark.asyncio
async def test_summary_command_uses_runtime_bot_username_when_env_username_is_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = CapturingProvider()
    monkeypatch.setattr(commands, "MessageRepository", lambda session: FakeRepository())
    message = FakeMessage("/summary@Home_ai_my_bot кратко перескажи, зачем нужен DNS")

    await commands.cmd_summary(
        message,  # type: ignore[arg-type]
        settings=Settings(telegram_bot_username="59144850"),
        db_session=object(),
        llm_provider=provider,
        bot=FakeBot(),
    )

    assert "кратко перескажи, зачем нужен DNS" in provider.rendered_prompt
    assert message.answers == ["готово"]


@pytest.mark.asyncio
async def test_summary_command_for_other_bot_is_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = CapturingProvider()
    monkeypatch.setattr(commands, "MessageRepository", lambda session: FakeRepository())
    message = FakeMessage("/summary@OtherBot кратко перескажи, зачем нужен DNS")

    await commands.cmd_summary(
        message,  # type: ignore[arg-type]
        settings=Settings(telegram_bot_username="Home_ai_my_bot"),
        db_session=object(),
        llm_provider=provider,
    )

    assert provider.rendered_prompt == ""
    assert message.answers == []
