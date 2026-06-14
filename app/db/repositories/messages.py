from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Message, MessageRole


class MessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add_message(
        self,
        *,
        chat_id: int,
        user_id: int | None,
        role: MessageRole,
        text: str,
        telegram_message_id: int | None = None,
    ) -> Message:
        message = Message(
            chat_id=chat_id,
            user_id=user_id,
            role=role,
            content=text,
            telegram_message_id=telegram_message_id,
        )
        self.session.add(message)
        await self.session.commit()
        await self.session.refresh(message)
        return message

    async def recent_messages(self, *, chat_id: int, limit: int) -> list[Message]:
        result = await self.session.execute(
            select(Message)
            .where(Message.chat_id == chat_id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(limit)
        )
        return list(reversed(result.scalars().all()))

    async def clear_chat(self, *, chat_id: int) -> None:
        await self.session.execute(delete(Message).where(Message.chat_id == chat_id))
        await self.session.commit()
