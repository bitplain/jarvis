from typing import Any

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

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
    await message.answer(
        "Статус: Stage 2 активен.\n"
        f"Guest Mode: {guest_status}\n"
        f"Guest access: {guest_access}"
    )


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
