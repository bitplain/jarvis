from typing import Any

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BusinessConnection, BusinessConnectionStatus
from app.db.repositories.messages import MessageRepository
from app.llm.base import LLMProviderError
from app.llm.factory import build_llm_provider
from app.llm.types import LLMMessage
from app.services.memory_service import MemoryService


async def cmd_start(message: Message) -> None:
    await message.answer("Jarvis готов. Пишите вопрос на русском языке.")


async def cmd_help(message: Message) -> None:
    await message.answer(
        "/reset — очистить память\n"
        "/models — модели\n"
        "/status — статус\n"
        "/summary — кратко пересказать последний переданный контекст\n"
        "/draft_reply — подготовить ответ\n"
        "/translate — перевести нормально\n"
        "/factcheck — проверить факты"
    )


async def cmd_status(message: Message, **data: Any) -> None:
    settings = data["settings"]
    personal_chat = "enabled" if settings.regular_assistant_enabled else "disabled"
    group_assistant = "enabled" if settings.group_assistant_enabled else "disabled"
    guest_status = "enabled" if settings.guest_mode_enabled else "disabled"
    guest_access = "admin-only" if settings.guest_mode_admin_only else "open"
    forwarded_status = "enabled" if settings.forwarded_message_assistant_enabled else "disabled"
    draft_status = "enabled" if settings.draft_reply_enabled else "disabled"
    business_mode = "enabled" if settings.business_mode_enabled else "optional/disabled"
    business_reply = "enabled" if settings.business_reply_enabled else "disabled"
    business_admin_only = "true" if settings.business_admin_only else "false"
    business_count, business_active_count = await resolve_business_counts(data)
    await message.answer(
        "Статус: Regular Assistant Mode активен.\n"
        f"Personal Chat: {personal_chat}\n"
        f"Group Assistant: {group_assistant}\n"
        f"Guest Mode: {guest_status}\n"
        f"Guest access: {guest_access}\n"
        f"Forwarded Assistant: {forwarded_status}\n"
        f"Draft Reply: {draft_status}\n"
        f"Business Mode: {business_mode}\n"
        f"Business Reply: {business_reply}\n"
        f"Business Admin Only: {business_admin_only}\n"
        f"Business Connections: {business_count}\n"
        f"Business Active Connections: {business_active_count}"
    )


async def _handle_context_command(
    message: Message,
    data: dict[str, Any],
    *,
    action: str,
) -> None:
    session = data.get("db_session")
    settings = data["settings"]
    if session is None:
        await message.answer("Контекст доступен только в runtime с БД.")
        return
    memory = MemoryService(MessageRepository(session), max_messages=settings.memory_max_messages)
    recent = await memory.recent_messages(chat_id=message.chat.id)
    if not recent:
        await message.answer(
            "Не вижу переданного контекста. Перешли сообщение боту или пришли текст."
        )
        return
    context = "\n".join(item.content for item in recent[-5:])
    provider = data.get("llm_provider") or build_llm_provider(settings)
    prompts = {
        "summary": "Кратко перескажи переданный контекст на русском.",
        "draft_reply": (
            "Подготовь вежливый черновик ответа на русском. Не утверждай, что отправил его."
        ),
        "translate": "Переведи переданный текст нормально на русский, сохрани смысл и тон.",
        "factcheck": "Проверь факты в тексте. Если не уверен, честно отметь, что нужна проверка.",
    }
    try:
        response = await provider.complete(
            [
                LLMMessage(
                    role="system",
                    content="Ты Jarvis в Regular Assistant Mode. Отвечай только на русском.",
                ),
                LLMMessage(role="user", content=f"{prompts[action]}\n\nКонтекст:\n{context}"),
            ]
        )
    except LLMProviderError:
        await message.answer("Не смог обработать контекст: временная ошибка модели.")
        return
    await message.answer(response.content.strip() or "Не смог подготовить ответ.")


async def cmd_summary(message: Message, **data: Any) -> None:
    await _handle_context_command(message, data, action="summary")


async def cmd_draft_reply(message: Message, **data: Any) -> None:
    await _handle_context_command(message, data, action="draft_reply")


async def cmd_translate(message: Message, **data: Any) -> None:
    await _handle_context_command(message, data, action="translate")


async def cmd_factcheck(message: Message, **data: Any) -> None:
    await _handle_context_command(message, data, action="factcheck")


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
    router.message(Command("summary"))(cmd_summary)
    router.message(Command("draft_reply"))(cmd_draft_reply)
    router.message(Command("translate"))(cmd_translate)
    router.message(Command("factcheck"))(cmd_factcheck)
    return router


router = build_router()
