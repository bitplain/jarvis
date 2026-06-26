from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Any, cast

from aiogram import F, Router
from aiogram.filters import Filter, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.middlewares.access import is_admin_user
from app.bot.routers.groups import GROUP_CHAT_TYPES, classify_group_message
from app.db.repositories.household_memory import HouseholdMemoryRepository
from app.db.repositories.telegram_access import TelegramAccessRepository
from app.services.household_memory_service import (
    SECRET_REJECTION_MESSAGE,
    HouseholdMemoryLimitExceeded,
    HouseholdMemorySecretRejected,
    HouseholdMemoryService,
)
from app.services.telegram_access_service import TelegramAccessService

MEMORY_CALLBACK_ADD = "mem:add"
MEMORY_CALLBACK_DELETE_PREFIX = "mem:del:"


class HouseholdMemoryInput(StatesGroup):
    add = State()


@dataclass(frozen=True)
class MemoryIntent:
    action: str
    text: str = ""


class PrivateHouseholdMemoryFilter(Filter):
    async def __call__(self, message: Message, **data: Any) -> dict[str, Any] | bool:
        del data
        if message.chat.type != "private" or not message.text:
            return False
        intent = parse_memory_intent(message.text)
        if intent is None:
            return False
        chat_id = message.from_user.id if message.from_user else message.chat.id
        return {
            "household_memory_intent": intent,
            "household_memory_scope": "private",
            "household_memory_chat_id": chat_id,
        }


class GroupHouseholdMemoryFilter(Filter):
    async def __call__(self, message: Message, **data: Any) -> dict[str, Any] | bool:
        if message.chat.type not in GROUP_CHAT_TYPES or not message.text:
            return False
        bot = data.get("bot")
        settings = data.get("settings")
        bot_user_id = None
        bot_username = getattr(settings, "telegram_bot_username", "")
        if bot is not None:
            me = await bot.get_me()
            bot_user_id = getattr(me, "id", None)
            bot_username = getattr(me, "username", None) or bot_username
        reply_user_id = None
        if message.reply_to_message and message.reply_to_message.from_user:
            reply_user_id = message.reply_to_message.from_user.id
        decision = classify_group_message(
            message.text,
            reply_user_id,
            str(bot_username),
            bot_user_id=bot_user_id,
        )
        if not decision.should_process:
            return False
        text = strip_group_trigger(message.text, str(bot_username), decision.matched_bot_username)
        intent = parse_memory_intent(text)
        if intent is None:
            return False
        return {
            "household_memory_intent": intent,
            "household_memory_scope": "group",
            "household_memory_chat_id": message.chat.id,
        }


def parse_memory_intent(text: str) -> MemoryIntent | None:
    normalized = text.strip()
    lowered = normalized.casefold()
    if lowered.startswith("запомни:"):
        return MemoryIntent("add", normalized.split(":", maxsplit=1)[1].strip())
    match = re.match(r"^запомни\s+что\s+(.+)$", normalized, flags=re.IGNORECASE)
    if match:
        return MemoryIntent("add", match.group(1).strip())
    if lowered in {"что ты помнишь?", "что ты помнишь", "что помнишь?", "что помнишь"}:
        return MemoryIntent("list")
    if lowered.startswith("забудь:"):
        return MemoryIntent("delete", normalized.split(":", maxsplit=1)[1].strip())
    return None


def strip_group_trigger(text: str, bot_username: str, matched_bot_username: bool) -> str:
    if not matched_bot_username:
        return text.strip()
    username = bot_username.strip().lstrip("@")
    if not username:
        return text.strip()
    pattern = rf"(?<![A-Za-z0-9_])@{re.escape(username)}(?![A-Za-z0-9_])"
    return re.sub(pattern, "", text, flags=re.IGNORECASE).strip()


async def handle_household_memory_message(
    message: Message,
    household_memory_intent: MemoryIntent,
    household_memory_scope: str,
    household_memory_chat_id: int,
    **data: Any,
) -> None:
    if not message.from_user:
        return
    service = _service(data)
    if service is None:
        await message.answer("Память временно недоступна: база данных не подключена.")
        return
    if household_memory_intent.action == "add":
        await _save_memory(
            message,
            service,
            scope_type=household_memory_scope,
            chat_id=household_memory_chat_id,
            user_id=message.from_user.id,
            text=household_memory_intent.text,
        )
        return
    if household_memory_intent.action == "list":
        memories = await service.list_memories(household_memory_scope, household_memory_chat_id)
        await message.answer(
            render_memory_list_html(memories),
            parse_mode="HTML",
            reply_markup=build_memory_keyboard(memories),
        )
        return
    if household_memory_intent.action == "delete":
        matches = await service.delete_memory_by_text(
            household_memory_scope,
            household_memory_chat_id,
            household_memory_intent.text,
            message.from_user.id,
        )
        if len(matches) == 1 and getattr(matches[0], "status", "") == "deleted":
            await message.answer("Забыл.")
            return
        if len(matches) > 1:
            await message.answer(
                "Нашёл несколько похожих записей. Выберите, что удалить:\n\n"
                f"{render_memory_list_html(matches)}",
                parse_mode="HTML",
                reply_markup=build_memory_keyboard(matches, add_button=False),
            )
            return
        await message.answer("Не нашёл такую запись в памяти.")


async def handle_household_memory_callback(
    callback: CallbackQuery,
    state: FSMContext,
    **data: Any,
) -> None:
    callback_data = callback.data or ""
    if callback.message is None:
        await callback.answer()
        return
    session = cast(AsyncSession | None, data.get("db_session"))
    if session is None:
        await callback.answer("Память временно недоступна.", show_alert=True)
        return
    if not await _is_callback_allowed(callback, session, data):
        if callback.message.chat.type in GROUP_CHAT_TYPES:
            await callback.answer()
        else:
            await callback.answer("Доступ запрещён.", show_alert=True)
        return
    if callback_data == MEMORY_CALLBACK_ADD:
        scope, chat_id = _callback_scope(callback)
        await state.set_state(HouseholdMemoryInput.add)
        await state.update_data(household_memory_scope=scope, household_memory_chat_id=chat_id)
        await callback.message.answer(
            "Что запомнить?\nДля отмены отправьте /cancel.",
        )
        await callback.answer()
        return
    if callback_data.startswith(MEMORY_CALLBACK_DELETE_PREFIX):
        service = _service(data)
        if service is None:
            await callback.answer("Память временно недоступна.", show_alert=True)
            return
        deleted = await service.delete_memory_by_id(
            callback_data.removeprefix(MEMORY_CALLBACK_DELETE_PREFIX),
            callback.from_user.id,
        )
        await callback.answer("Удалено." if deleted is not None else "Уже удалено.")
        scope, chat_id = _callback_scope(callback)
        memories = await service.list_memories(scope, chat_id)
        await callback.message.answer(
            render_memory_list_html(memories),
            parse_mode="HTML",
            reply_markup=build_memory_keyboard(memories),
        )


async def handle_household_memory_input_message(
    message: Message,
    state: FSMContext,
    **data: Any,
) -> None:
    if not message.from_user:
        return
    text = (message.text or message.caption or "").strip()
    if text.casefold() == "/cancel":
        await state.clear()
        await message.answer("Ввод отменён.")
        return
    service = _service(data)
    if service is None:
        await message.answer("Память временно недоступна: база данных не подключена.")
        return
    state_data = await state.get_data()
    scope = str(state_data.get("household_memory_scope") or _message_scope(message)[0])
    chat_id = int(state_data.get("household_memory_chat_id") or _message_scope(message)[1])
    await _save_memory(
        message,
        service,
        scope_type=scope,
        chat_id=chat_id,
        user_id=message.from_user.id,
        text=text,
    )
    await state.clear()


async def _save_memory(
    message: Message,
    service: HouseholdMemoryService,
    *,
    scope_type: str,
    chat_id: int,
    user_id: int,
    text: str,
) -> None:
    try:
        await service.add_memory(scope_type, chat_id, user_id, text)
    except HouseholdMemorySecretRejected:
        await message.answer(SECRET_REJECTION_MESSAGE)
        return
    except HouseholdMemoryLimitExceeded:
        await message.answer("В этом чате уже сохранено слишком много фактов.")
        return
    except ValueError as exc:
        if "too_long" in str(exc):
            await message.answer("Слишком длинно. Лимит: 500 символов.")
        else:
            await message.answer("Не вижу, что запомнить.")
        return
    await message.answer("Сохранил.")


def render_memory_list_html(memories: list[Any]) -> str:
    lines = ["<b>Память Jarvis</b>", ""]
    if not memories:
        lines.append("Пока ничего не помню для этого чата.")
        return "\n".join(lines)
    for index, memory in enumerate(memories, start=1):
        lines.append(f"{index}. {html.escape(str(memory.text))}")
    return "\n".join(lines)


def build_memory_keyboard(memories: list[Any], *, add_button: bool = True) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    delete_buttons = [
        InlineKeyboardButton(
            text=f"🗑 {index}",
            callback_data=f"{MEMORY_CALLBACK_DELETE_PREFIX}{memory.id}",
        )
        for index, memory in enumerate(memories, start=1)
    ]
    for offset in range(0, len(delete_buttons), 4):
        rows.append(delete_buttons[offset : offset + 4])
    if add_button:
        rows.append([InlineKeyboardButton(text="➕ Запомнить", callback_data=MEMORY_CALLBACK_ADD)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _message_scope(message: Message) -> tuple[str, int]:
    if message.chat.type in GROUP_CHAT_TYPES:
        return "group", message.chat.id
    return "private", message.from_user.id if message.from_user else message.chat.id


def _callback_scope(callback: CallbackQuery) -> tuple[str, int]:
    if callback.message is not None and callback.message.chat.type in GROUP_CHAT_TYPES:
        return "group", callback.message.chat.id
    return "private", callback.from_user.id


def _service(data: dict[str, Any]) -> HouseholdMemoryService | None:
    injected = data.get("household_memory_service")
    if isinstance(injected, HouseholdMemoryService) or injected is not None:
        return cast(HouseholdMemoryService, injected)
    session = cast(AsyncSession | None, data.get("db_session"))
    if session is None:
        return None
    return HouseholdMemoryService(HouseholdMemoryRepository(session))


async def _is_callback_allowed(
    callback: CallbackQuery,
    session: AsyncSession,
    data: dict[str, Any],
) -> bool:
    settings = data["settings"]
    user_id = callback.from_user.id
    if is_admin_user(user_id, settings.admin_ids):
        return True
    access = TelegramAccessService(TelegramAccessRepository(session), admin_ids=settings.admin_ids)
    if not await access.is_allowed_user(user_id):
        return False
    if callback.message is None or callback.message.chat.type not in GROUP_CHAT_TYPES:
        return True
    return await access.is_allowed_group(callback.message.chat.id)


def build_router() -> Router:
    router = Router(name="household_memory")
    router.message(StateFilter(HouseholdMemoryInput.add))(handle_household_memory_input_message)
    router.message(PrivateHouseholdMemoryFilter())(handle_household_memory_message)
    router.message(GroupHouseholdMemoryFilter())(handle_household_memory_message)
    router.callback_query(F.data == MEMORY_CALLBACK_ADD)(handle_household_memory_callback)
    router.callback_query(F.data.startswith(MEMORY_CALLBACK_DELETE_PREFIX))(
        handle_household_memory_callback
    )
    return router


router = build_router()
