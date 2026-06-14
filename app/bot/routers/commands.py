from typing import Any

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BusinessConnection, BusinessConnectionStatus
from app.db.repositories.messages import MessageRepository
from app.services.memory_service import MemoryService


async def cmd_start(message: Message) -> None:
    await message.answer("Jarvis готов. Пишите вопрос на русском языке.")


async def cmd_help(message: Message) -> None:
    await message.answer("/reset — очистить память\n/models — модели\n/status — статус")


async def cmd_status(message: Message, **data: Any) -> None:
    settings = data["settings"]
    guest_status = "enabled" if settings.guest_mode_enabled else "disabled"
    guest_access = "admin-only" if settings.guest_mode_admin_only else "open"
    business_mode = "enabled" if settings.business_mode_enabled else "disabled"
    business_reply = "enabled" if settings.business_reply_enabled else "disabled"
    business_admin_only = "true" if settings.business_admin_only else "false"
    business_count, business_active_count = await resolve_business_counts(data)
    await message.answer(
        "Статус: Stage 2 активен.\n"
        f"Guest Mode: {guest_status}\n"
        f"Guest access: {guest_access}\n"
        f"Business Mode: {business_mode}\n"
        f"Business Reply: {business_reply}\n"
        f"Business Admin Only: {business_admin_only}\n"
        f"Business Connections: {business_count}\n"
        f"Business Active Connections: {business_active_count}"
    )


async def resolve_business_counts(data: dict[str, Any]) -> tuple[int, int]:
    injected = data.get("business_status_counts")
    if isinstance(injected, tuple) and len(injected) == 2:
        return int(injected[0]), int(injected[1])
    session = data.get("db_session")
    if not isinstance(session, AsyncSession):
        return 0, 0
    total_result = await session.execute(select(func.count(BusinessConnection.id)))
    active_result = await session.execute(
        select(func.count(BusinessConnection.id)).where(
            BusinessConnection.status == BusinessConnectionStatus.ENABLED,
            BusinessConnection.is_enabled.is_(True),
        )
    )
    return int(total_result.scalar_one()), int(active_result.scalar_one())


async def cmd_models(message: Message, **data: Any) -> None:
    settings = data["settings"]
    current = settings.selected_model or "не задана"
    await message.answer(f"Текущая модель: {current}")


async def cmd_reset(message: Message, **data: Any) -> None:
    session = data.get("db_session")
    settings = data["settings"]
    if session is None:
        await message.answer("Память очищается только в runtime с БД.")
        return
    service = MemoryService(MessageRepository(session), max_messages=settings.memory_max_messages)
    await service.reset_chat(chat_id=message.chat.id)
    await message.answer("Память этого чата очищена.")


def build_router() -> Router:
    router = Router(name="commands")
    router.message(Command("start"))(cmd_start)
    router.message(Command("help"))(cmd_help)
    router.message(Command("status"))(cmd_status)
    router.message(Command("models"))(cmd_models)
    router.message(Command("reset"))(cmd_reset)
    return router


router = build_router()
