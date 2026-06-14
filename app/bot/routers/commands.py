from typing import Any

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.db.repositories.messages import MessageRepository
from app.services.memory_service import MemoryService

router = Router(name="commands")


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer("Jarvis готов. Пишите вопрос на русском языке.")


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer("/reset — очистить память\n/models — модели\n/status — статус")


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    await message.answer("Статус: каркас Stage 1 активен.")


@router.message(Command("models"))
async def cmd_models(message: Message, **data: Any) -> None:
    settings = data["settings"]
    current = settings.selected_model or "не задана"
    await message.answer(f"Текущая модель: {current}")


@router.message(Command("reset"))
async def cmd_reset(message: Message, **data: Any) -> None:
    session = data.get("db_session")
    settings = data["settings"]
    if session is None:
        await message.answer("Память очищается только в runtime с БД.")
        return
    service = MemoryService(MessageRepository(session), max_messages=settings.memory_max_messages)
    await service.reset_chat(chat_id=message.chat.id)
    await message.answer("Память этого чата очищена.")
