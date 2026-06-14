import logging
from typing import Any, cast

from aiogram import Router
from aiogram.types import InlineQueryResultArticle, InputTextMessageContent, Message, Update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.services.guest_service import (
    GuestMessageRepository,
    GuestMessageRepositoryProtocol,
    GuestRequest,
    GuestService,
    InMemoryGuestMessageRepository,
)

logger = logging.getLogger(__name__)

MAX_GUEST_ANSWER_LENGTH = 4096


def _message_text(message: Message | None) -> str | None:
    if message is None:
        return None
    return message.text or message.caption


def build_guest_answer_result(text: str) -> InlineQueryResultArticle:
    safe_text = text[:MAX_GUEST_ANSWER_LENGTH]
    return InlineQueryResultArticle(
        id="jarvis-guest-response",
        title="Ответ Jarvis",
        input_message_content=InputTextMessageContent(message_text=safe_text),
    )


def extract_guest_request(message: Message, update: Update | None) -> GuestRequest:
    caller_user = message.guest_bot_caller_user or message.from_user
    caller_chat = message.guest_bot_caller_chat
    return GuestRequest(
        telegram_update_id=update.update_id if update else None,
        guest_query_id=message.guest_query_id,
        caller_user_id=caller_user.id if caller_user else None,
        caller_chat_id=caller_chat.id if caller_chat else None,
        request_text=_message_text(message) or "",
        replied_text=_message_text(message.reply_to_message),
    )


def resolve_guest_repository(data: dict[str, Any]) -> GuestMessageRepositoryProtocol:
    repository = data.get("guest_repository")
    if repository is not None:
        return cast(GuestMessageRepositoryProtocol, repository)
    session = data.get("db_session")
    if isinstance(session, AsyncSession):
        return GuestMessageRepository(session)
    return InMemoryGuestMessageRepository()


async def handle_guest_message(message: Message | None, **data: Any) -> None:
    if message is None:
        return
    settings: Settings = data["settings"]
    bot = data["bot"]
    update = data.get("event_update")
    request = extract_guest_request(message, update if isinstance(update, Update) else None)
    service = GuestService(
        settings,
        repository=resolve_guest_repository(data),
        provider=data.get("llm_provider"),
    )
    result = await service.handle(request)
    if not result.should_answer or not request.guest_query_id or not result.text:
        return
    try:
        await bot.answer_guest_query(
            guest_query_id=request.guest_query_id,
            result=build_guest_answer_result(result.text),
        )
    except Exception as exc:
        logger.warning("guest_answer_failed", extra={"error_type": type(exc).__name__})


def build_router() -> Router:
    router = Router(name="guest")
    router.guest_message()(handle_guest_message)
    return router


router = build_router()
