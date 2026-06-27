import logging
from typing import Any

from aiogram import F, Router
from aiogram.types import Message

from app.bot.thinking import THINKING_TEXT
from app.core.logging import safe_extra
from app.db.models import MessageRole
from app.db.repositories.messages import MessageRepository
from app.services.memory_service import MemoryService
from app.services.regular_assistant_service import (
    DRAFT_REPLY_EMPTY_CONTEXT,
    RegularAssistantService,
    is_draft_reply_request,
)
from app.services.web_search.intent import parse_web_search_intent

logger = logging.getLogger(__name__)


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
    memory = data.get("memory_service")
    if not isinstance(memory, MemoryService):
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

    if session is None and memory is None:
        await message.answer("База данных временно недоступна.")
        return
    if memory is None:
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
        text=text,
        telegram_message_id=message.message_id,
    )
    if redis is not None:
        web_search_intent = parse_web_search_intent(text)
        if web_search_intent is not None and not await _web_search_rate_limit_allowed(
            redis,
            user_id=message.from_user.id,
        ):
            await message.answer("Слишком много запросов к интернет-поиску. Попробуйте позже.")
            return
        job_id = f"llm:{message.chat.id}:{message.message_id}"
        payload: dict[str, Any] = {
            "chat_id": message.chat.id,
            "user_id": message.from_user.id,
            "private": True,
        }
        if web_search_intent is not None:
            payload["web_search"] = {"query": web_search_intent.query}
        await redis.enqueue_job(
            "process_llm_message",
            payload,
            _job_id=job_id,
        )
        log_kwargs: dict[str, Any] = safe_extra(
            chat_type=message.chat.type,
            chat_id_masked="***" + str(message.chat.id)[-4:],
            user_id_masked="***" + str(message.from_user.id)[-4:],
            message_id=message.message_id,
            private=True,
            job_id=job_id,
        )
        logger.info("telegram_llm_job_enqueued", **log_kwargs)
        if not (
            settings.streaming_enabled
            and settings.streaming_private_draft_enabled
            and settings.telegram_private_draft_streaming_enabled
        ):
            await message.answer(THINKING_TEXT)
        return
    await message.answer("Worker временно недоступен.")


async def _web_search_rate_limit_allowed(redis: object, *, user_id: int) -> bool:
    if not hasattr(redis, "incr"):
        return True
    key = f"web_search:rate:{user_id}"
    try:
        count = await redis.incr(key)  # type: ignore[attr-defined]
        if count == 1 and hasattr(redis, "expire"):
            await redis.expire(key, 600)  # type: ignore[attr-defined]
        return int(count) <= 10
    except Exception as exc:
        logger.warning(
            "web_search_rate_limit_unavailable",
            extra={"error_type": type(exc).__name__},
        )
        return True


def build_router() -> Router:
    router = Router(name="private")
    router.message(F.chat.type == "private")(handle_private_text)
    return router


router = build_router()
