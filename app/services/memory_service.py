from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from app.db.models import MessageRole
from app.llm.types import LLMMessage


@dataclass
class MemoryMessage:
    chat_id: int
    user_id: int | None
    role: MessageRole
    content: str


class StoredMessage(Protocol):
    role: MessageRole
    content: str


class MessageRepositoryProtocol(Protocol):
    async def add_message(
        self,
        *,
        chat_id: int,
        user_id: int | None,
        role: MessageRole,
        text: str,
        telegram_message_id: int | None = None,
    ) -> object:
        ...

    async def recent_messages(self, *, chat_id: int, limit: int) -> Sequence[StoredMessage]:
        ...

    async def clear_chat(self, *, chat_id: int) -> None:
        ...


class InMemoryMessageRepository:
    def __init__(self) -> None:
        self.messages: list[MemoryMessage] = []

    async def add_message(
        self,
        *,
        chat_id: int,
        user_id: int | None,
        role: MessageRole,
        text: str,
        telegram_message_id: int | None = None,
    ) -> MemoryMessage:
        del telegram_message_id
        message = MemoryMessage(chat_id=chat_id, user_id=user_id, role=role, content=text)
        self.messages.append(message)
        return message

    async def recent_messages(self, *, chat_id: int, limit: int) -> Sequence[MemoryMessage]:
        selected = [message for message in self.messages if message.chat_id == chat_id]
        return selected[-limit:]

    async def clear_chat(self, *, chat_id: int) -> None:
        self.messages = [message for message in self.messages if message.chat_id != chat_id]


class MemoryService:
    system_prompt = (
        "Ты Jarvis. Отвечай только на русском языке. "
        "Отвечай кратко, полезно и структурированно. "
        "Если не знаешь ответ, честно скажи, что не знаешь. Не выдумывай факты."
    )

    def __init__(self, repository: MessageRepositoryProtocol, *, max_messages: int) -> None:
        self.repository = repository
        self.max_messages = max_messages

    async def add_message(
        self,
        *,
        chat_id: int,
        user_id: int | None,
        role: MessageRole,
        text: str,
        telegram_message_id: int | None = None,
    ) -> None:
        await self.repository.add_message(
            chat_id=chat_id,
            user_id=user_id,
            role=role,
            text=text,
            telegram_message_id=telegram_message_id,
        )

    async def recent_messages(self, *, chat_id: int) -> Sequence[StoredMessage]:
        return await self.repository.recent_messages(chat_id=chat_id, limit=self.max_messages)

    async def build_context(self, *, chat_id: int) -> list[LLMMessage]:
        recent = await self.recent_messages(chat_id=chat_id)
        messages = [LLMMessage(role="system", content=self.system_prompt)]
        for message in recent:
            messages.append(LLMMessage(role=message.role.value, content=message.content))
        return messages

    async def reset_chat(self, *, chat_id: int) -> None:
        await self.repository.clear_chat(chat_id=chat_id)
