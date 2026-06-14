from typing import Any

from aiogram import Router
from aiogram.types import Message

from app.db.models import MessageRole
from app.db.repositories.messages import MessageRepository
from app.services.memory_service import MemoryService

router = Router(name="private")


@router.message()
async def handle_private_text(message: Message, **data: Any) -> None:
    if message.chat.type != "private" or not message.text or not message.from_user:
        return
    session = data.get("db_session")
    redis = data.get("redis")
    settings = data["settings"]
    if session is None:
        await message.answer("База данных временно недоступна.")
        return
    memory = MemoryService(MessageRepository(session), max_messages=settings.memory_max_messages)
    await memory.add_message(
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        role=MessageRole.USER,
        text=message.text,
        telegram_message_id=message.message_id,
    )
    if redis is not None:
        await redis.enqueue_job(
            "process_llm_message",
            {
                "chat_id": message.chat.id,
                "user_id": message.from_user.id,
                "private": True,
            },
        )
        await message.answer("Принял. Готовлю ответ.")
        return
    await message.answer("Worker временно недоступен.")
