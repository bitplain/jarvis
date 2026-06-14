from dataclasses import dataclass

from app.db.models import MessageRole
from app.services.memory_service import MemoryService


@dataclass(frozen=True)
class IncomingChatMessage:
    chat_id: int
    user_id: int
    text: str
    telegram_message_id: int | None = None


class ChatService:
    def __init__(self, memory: MemoryService) -> None:
        self.memory = memory

    async def record_user_message(self, message: IncomingChatMessage) -> None:
        await self.memory.add_message(
            chat_id=message.chat_id,
            user_id=message.user_id,
            role=MessageRole.USER,
            text=message.text,
            telegram_message_id=message.telegram_message_id,
        )

    async def record_assistant_message(self, *, chat_id: int, text: str) -> None:
        await self.memory.add_message(
            chat_id=chat_id,
            user_id=None,
            role=MessageRole.ASSISTANT,
            text=text,
        )
