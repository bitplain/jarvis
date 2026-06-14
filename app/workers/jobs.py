import logging
import time
from typing import Any

from aiogram import Bot
from aiogram.enums import ChatAction

from app.bot.streaming.buffer import StreamBuffer
from app.bot.streaming.telegram_draft import TelegramDraftNotAvailable, TelegramPrivateDraftSink
from app.core.config import get_settings
from app.db.models import MessageRole
from app.db.repositories.messages import MessageRepository
from app.db.session import SessionLocal
from app.llm.base import LLMProviderError
from app.llm.factory import build_llm_provider
from app.services.memory_service import MemoryService

logger = logging.getLogger(__name__)
USER_ERROR_MESSAGE = "Не получилось подготовить ответ. Попробуйте позже."


async def process_llm_message(ctx: dict[str, Any], payload: dict[str, Any]) -> None:
    del ctx
    settings = get_settings()
    bot = Bot(token=settings.telegram_bot_token)
    chat_id = int(payload["chat_id"])
    is_private = bool(payload.get("private"))
    async with SessionLocal() as session:
        memory = MemoryService(
            MessageRepository(session),
            max_messages=settings.memory_max_messages,
        )
        messages = await memory.build_context(chat_id=chat_id)
        provider = build_llm_provider(settings)
        final_text = ""
        try:
            if is_private:
                buffer = StreamBuffer(min_interval_seconds=0.8, min_chars=100)
                draft = TelegramPrivateDraftSink(bot)
                async for chunk in provider.stream(messages):
                    final_text += chunk.content
                    if buffer.should_flush(now=time.monotonic(), text=final_text):
                        try:
                            await draft.publish(chat_id=chat_id, text=final_text)
                            buffer.mark_flushed(now=time.monotonic())
                        except TelegramDraftNotAvailable:
                            await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
                if not final_text:
                    response = await provider.complete(messages)
                    final_text = response.content
            else:
                await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
                response = await provider.complete(messages)
                final_text = response.content
        except LLMProviderError as exc:
            logger.warning("llm_failed", extra={"error_code": exc.code})
            final_text = USER_ERROR_MESSAGE
        await bot.send_message(chat_id=chat_id, text=final_text)
        await memory.add_message(
            chat_id=chat_id,
            user_id=None,
            role=MessageRole.ASSISTANT,
            text=final_text,
        )
    await bot.session.close()
