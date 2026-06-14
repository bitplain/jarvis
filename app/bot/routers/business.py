from typing import Any, cast

from aiogram import Router
from aiogram.types import BusinessConnection, BusinessMessagesDeleted, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.adapters.business_api import AiogramBusinessApi, business_connection_event_from_aiogram
from app.core.config import Settings
from app.services.business_service import (
    BusinessMessageRepository,
    BusinessMessageRequest,
    BusinessRepositoryProtocol,
    BusinessService,
    DeletedBusinessMessagesRequest,
    InMemoryBusinessRepository,
)

BUSINESS_UPDATE_KEYS = {
    "business_connection",
    "business_message",
    "edited_business_message",
    "deleted_business_messages",
}


def _message_text(message: Message | None) -> str | None:
    if message is None:
        return None
    return message.text or message.caption


def _reply_to_message_id(message: Message) -> int | None:
    if message.reply_to_message is None:
        return None
    return message.reply_to_message.message_id


def extract_business_message_request(message: Message) -> BusinessMessageRequest:
    return BusinessMessageRequest(
        business_connection_id=message.business_connection_id or "",
        telegram_message_id=message.message_id,
        chat_id=message.chat.id,
        from_user_id=message.from_user.id if message.from_user else None,
        text=_message_text(message),
        reply_to_message_id=_reply_to_message_id(message),
    )


def extract_deleted_business_messages_request(
    event: BusinessMessagesDeleted,
) -> DeletedBusinessMessagesRequest:
    return DeletedBusinessMessagesRequest(
        business_connection_id=event.business_connection_id,
        chat_id=event.chat.id,
        message_ids=list(event.message_ids),
    )


def resolve_business_repository(data: dict[str, Any]) -> BusinessRepositoryProtocol:
    repository = data.get("business_repository")
    if repository is not None:
        return cast(BusinessRepositoryProtocol, repository)
    session = data.get("db_session")
    if isinstance(session, AsyncSession):
        return BusinessMessageRepository(session)
    return InMemoryBusinessRepository()


def build_business_service(data: dict[str, Any]) -> BusinessService:
    settings: Settings = data["settings"]
    bot = data.get("bot")
    return BusinessService(
        settings,
        repository=resolve_business_repository(data),
        provider=data.get("llm_provider"),
        business_api=AiogramBusinessApi(bot) if bot is not None else None,
    )


async def handle_business_connection(
    business_connection: BusinessConnection | None,
    **data: Any,
) -> None:
    if business_connection is None:
        return
    service = build_business_service(data)
    await service.handle_connection(business_connection_event_from_aiogram(business_connection))


async def handle_business_message(
    message: Message | None,
    **data: Any,
) -> None:
    if message is None:
        return
    service = build_business_service(data)
    await service.handle_business_message(extract_business_message_request(message))


async def handle_edited_business_message(
    message: Message | None,
    **data: Any,
) -> None:
    if message is None:
        return
    service = build_business_service(data)
    await service.handle_edited_business_message(extract_business_message_request(message))


async def handle_deleted_business_messages(
    deleted_business_messages: BusinessMessagesDeleted | None,
    **data: Any,
) -> None:
    if deleted_business_messages is None:
        return
    service = build_business_service(data)
    await service.handle_deleted_business_messages(
        extract_deleted_business_messages_request(deleted_business_messages)
    )


async def secretary_mode_not_implemented() -> None:
    raise NotImplementedError("Autonomous Secretary Mode не реализован в Stage 3A.")


def build_router() -> Router:
    router = Router(name="business")
    router.business_connection()(handle_business_connection)
    router.business_message()(handle_business_message)
    router.edited_business_message()(handle_edited_business_message)
    router.deleted_business_messages()(handle_deleted_business_messages)
    return router


router = build_router()
