from typing import Any

from aiogram import F, Router
from aiogram.enums import ChatAction
from aiogram.types import Message

from app.db.models import MessageRole
from app.db.repositories.messages import MessageRepository
from app.services.memory_service import MemoryService


def should_answer_group_message(
    text: str | None,
    reply_to_user_id: int | None,
    bot_username: str,
    *,
    bot_user_id: int | None = None,
) -> bool:
    if not text:
        return False
    if bot_username and f"@{bot_username.lower()}" in text.lower():
        return True
    return bot_user_id is not None and reply_to_user_id == bot_user_id


async def handle_group_message(message: Message, **data: Any) -> None:
    if message.chat.type not in {"group", "supergroup"} or not message.from_user:
        return
    settings = data["settings"]
    if not settings.group_assistant_enabled:
        return
    bot = data["bot"]
    reply_user_id = None
    if message.reply_to_message and message.reply_to_message.from_user:
        reply_user_id = message.reply_to_message.from_user.id
    bot_user_id = None
    me = await bot.get_me()
    bot_user_id = me.id
    if not should_answer_group_message(
        message.text,
        reply_user_id,
        settings.telegram_bot_username,
        bot_user_id=bot_user_id,
    ):
        return
    memory = data.get("memory_service")
    if not isinstance(memory, MemoryService):
        session = data.get("db_session")
        if session is None:
            await message.answer("База данных временно недоступна.")
            return
        memory = MemoryService(
            MessageRepository(session),
            max_messages=settings.memory_max_messages,
        )
    await memory.add_message(
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        role=MessageRole.USER,
        text=message.text or "",
        telegram_message_id=message.message_id,
    )
    redis = data.get("redis")
    if redis is None:
        await message.answer("Worker временно недоступен.")
        return
    await redis.enqueue_job(
        "process_llm_message",
        {
            "chat_id": message.chat.id,
            "user_id": message.from_user.id,
            "private": False,
        },
    )
    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)
    await message.answer("Принял. Готовлю групповой ответ.")


def build_router() -> Router:
    router = Router(name="groups")
    router.message(F.chat.type.in_({"group", "supergroup"}))(handle_group_message)
    return router


router = build_router()
