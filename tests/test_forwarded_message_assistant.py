from typing import Any

import pytest

from app.bot.routers.private import handle_private_text
from app.core.config import Settings
from app.db.models import MessageRole
from app.llm.types import LLMMessage, LLMResponse
from app.services.memory_service import InMemoryMessageRepository, MemoryService
from app.services.regular_assistant_service import FORWARDED_ACTIONS_TEXT, RegularAssistantService


class FakeChat:
    type = "private"
    id = 123


class FakeUser:
    id = 100500


class FakeMessage:
    def __init__(
        self,
        *,
        text: str,
        forward_origin: object | None = None,
        message_id: int = 7,
    ) -> None:
        self.chat = FakeChat()
        self.from_user = FakeUser()
        self.text = text
        self.caption = None
        self.forward_origin = forward_origin
        self.forward_date = None
        self.forward_from = None
        self.forward_from_chat = None
        self.forward_sender_name = None
        self.message_id = message_id
        self.answers: list[str] = []

    async def answer(self, text: str, **kwargs: Any) -> None:
        self.answers.append(text)


class WorkingProvider:
    name = "yandex"

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        rendered = "\n".join(message.content for message in messages)
        assert "текст клиента" in rendered
        return LLMResponse(content="Черновик ответа пользователю.", provider=self.name, model="m")

    async def stream(self, messages: list[LLMMessage]):
        yield "unused"

    async def list_models(self) -> list[str]:
        return ["m"]


@pytest.mark.asyncio
async def test_forwarded_message_is_saved_as_context_and_actions_are_offered() -> None:
    repository = InMemoryMessageRepository()
    memory = MemoryService(repository, max_messages=10)
    service = RegularAssistantService(Settings(), memory=memory, provider=WorkingProvider())
    message = FakeMessage(text="важное пересланное сообщение", forward_origin=object())

    result = await service.handle_forwarded_message(
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        telegram_message_id=message.message_id,
        text=message.text,
    )

    assert result.text == FORWARDED_ACTIONS_TEXT
    assert repository.messages[0].role == MessageRole.USER
    assert "Пересланное сообщение" in repository.messages[0].content
    assert "важное пересланное сообщение" in repository.messages[0].content


@pytest.mark.asyncio
async def test_private_handler_processes_forwarded_message_before_worker_queue() -> None:
    repository = InMemoryMessageRepository()
    memory = MemoryService(repository, max_messages=10)
    service = RegularAssistantService(Settings(), memory=memory, provider=WorkingProvider())
    message = FakeMessage(text="пересланный текст", forward_origin=object())

    await handle_private_text(
        message,  # type: ignore[arg-type]
        settings=Settings(),
        regular_assistant_service=service,
        redis=object(),
    )

    assert message.answers == [FORWARDED_ACTIONS_TEXT]
    assert "пересланный текст" in repository.messages[0].content


@pytest.mark.asyncio
async def test_private_handler_returns_draft_reply_without_sending_as_user() -> None:
    repository = InMemoryMessageRepository()
    memory = MemoryService(repository, max_messages=10)
    service = RegularAssistantService(Settings(), memory=memory, provider=WorkingProvider())
    message = FakeMessage(text="Ответь на это:\nтекст клиента")

    await handle_private_text(
        message,  # type: ignore[arg-type]
        settings=Settings(),
        regular_assistant_service=service,
    )

    assert message.answers == ["Черновик ответа пользователю."]
    assert "текст клиента" in repository.messages[0].content
