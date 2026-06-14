from typing import Any

from aiogram import Router
from aiogram.types import Message

from app.db.models import MessageRole
from app.db.repositories.messages import MessageRepository
from app.services.memory_service import MemoryService
from app.services.regular_assistant_service import (
    DRAFT_REPLY_EMPTY_CONTEXT,
    RegularAssistantService,
    is_draft_reply_request,
)


def is_forwarded_message(message: Message) -> bool:
    return any(
        getattr(message, field_name, None) is not None
        for field_name in (
            "forward_origin",
            "forward_date",
            "forward_from",
            "forward_from_chat",
            "forward_sender_name",
        )
    )


def _message_text(message: Message) -> str | None:
    return message.text or message.caption


def resolve_regular_assistant_service(
    *,
    message: Message,
    data: dict[str, Any],
    memory: MemoryService | None,
) -> RegularAssistantService:
    injected = data.get("regular_assistant_service")
    if isinstance(injected, RegularAssistantService):
        return injected
    return RegularAssistantService(
        data["settings"],
        memory=memory,
        provider=data.get("llm_provider"),
    )


async def handle_private_text(message: Message, **data: Any) -> None:
    text = _message_text(message)
    if message.chat.type != "private" or not text or not message.from_user:
        return
    session = data.get("db_session")
    redis = data.get("redis")
    settings = data["settings"]
    memory = None
    if session is not None:
        memory = MemoryService(
            MessageRepository(session),
            max_messages=settings.memory_max_messages,
        )
    if "regular_assistant_service" in data:
        memory = None

    service = resolve_regular_assistant_service(message=message, data=data, memory=memory)
    if (
        settings.regular_assistant_enabled
        and settings.forwarded_message_assistant_enabled
        and is_forwarded_message(message)
    ):
        result = await service.handle_forwarded_message(
            chat_id=message.chat.id,
            user_id=message.from_user.id,
            telegram_message_id=message.message_id,
            text=text,
        )
        await message.answer(result.text)
        return

    draft_text = is_draft_reply_request(text)
    if (
        settings.regular_assistant_enabled
        and settings.draft_reply_enabled
        and draft_text is not None
    ):
        result = await service.handle_draft_reply(
            chat_id=message.chat.id,
            user_id=message.from_user.id,
            telegram_message_id=message.message_id,
            client_text=draft_text,
        )
        await message.answer(result.text)
        return
    if text.strip().lower().startswith("ответь на это:"):
        await message.answer(DRAFT_REPLY_EMPTY_CONTEXT)
        return

    if session is None:
        await message.answer("База данных временно недоступна.")
        return
    if memory is None:
        memory = MemoryService(
            MessageRepository(session),
            max_messages=settings.memory_max_messages,
        )
    await memory.add_message(
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        role=MessageRole.USER,
        text=text,
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


def build_router() -> Router:
    router = Router(name="private")
    router.message()(handle_private_text)
    return router


router = build_router()
