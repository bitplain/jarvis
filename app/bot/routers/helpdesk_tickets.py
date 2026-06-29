from __future__ import annotations

import logging
from typing import Any, cast

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.middlewares.access import GROUP_CHAT_TYPES, is_admin_user
from app.core.config import Settings
from app.db.repositories.helpdesk_ticket_work_items import HelpdeskTicketWorkItemRepository
from app.db.repositories.telegram_access import TelegramAccessRepository
from app.services.helpdesk_ticket_workflow import (
    DONE,
    IN_WORK,
    HelpdeskTicketWorkflowService,
    build_in_work_keyboard,
    build_ticket_list_keyboard,
    format_helpdesk_in_work_list_html,
)
from app.services.telegram_access_service import TelegramAccessService

logger = logging.getLogger(__name__)
HELPDESK_TICKET_COMMANDS = ("ticket",)


async def cmd_ticket(message: Message, **data: Any) -> None:
    settings = cast(Settings, data["settings"])
    bot_username = await _resolve_bot_username(data, settings.telegram_bot_username)
    if _is_command_for_other_bot(message, bot_username):
        return
    if not await _is_message_allowed(message, data):
        if getattr(message.chat, "type", "private") == "private":
            await message.answer("Доступ запрещён.")
        return
    service = await _workflow_service(data)
    if service is None:
        await message.answer("База данных временно недоступна.")
        return
    target_chat_id = _target_helpdesk_chat_id(message, settings)
    items = await service.list_in_work(telegram_chat_id=target_chat_id)
    reply_markup = build_ticket_list_keyboard(items)
    if reply_markup is None:
        await message.answer(format_helpdesk_in_work_list_html(items), parse_mode="HTML")
        return
    await message.answer(
        format_helpdesk_in_work_list_html(items),
        parse_mode="HTML",
        reply_markup=reply_markup,
    )


async def handle_helpdesk_ticket_callback(callback: CallbackQuery, **data: Any) -> None:
    callback_data = callback.data or ""
    if not await _is_callback_allowed(callback, data):
        await callback.answer("Доступ запрещён.", show_alert=True)
        return
    service = await _workflow_service(data)
    if service is None:
        await callback.answer("База данных временно недоступна.", show_alert=True)
        return
    parts = callback_data.split(":")
    if len(parts) < 3:
        await callback.answer("Неизвестная кнопка.", show_alert=True)
        return
    action = parts[1]
    item_id = parts[2]
    telegram_chat_id = _callback_chat_id(callback, data)
    actor_user_id = callback.from_user.id if callback.from_user else 0
    if action == "take":
        item = await service.take(
            item_id,
            actor_user_id=actor_user_id,
            telegram_chat_id=telegram_chat_id,
        )
        if item is None:
            await callback.answer("Заявка не найдена.", show_alert=True)
            return
        await _edit_callback_message(
            callback,
            text=f"Заявка GLPI #{item.glpi_ticket_id} взята в работу.",
            reply_markup=build_in_work_keyboard(item.id) if item.status == IN_WORK else None,
        )
        return
    if action == "done":
        item = await service.mark_done(
            item_id,
            actor_user_id=actor_user_id,
            telegram_chat_id=telegram_chat_id,
        )
        if item is None:
            await callback.answer("Заявка не найдена.", show_alert=True)
            return
        await _edit_callback_message(
            callback,
            text=f"Заявка GLPI #{item.glpi_ticket_id} закрыта.",
            reply_markup=None,
        )
        return
    if action == "snooze":
        minutes = _minutes_from_callback(parts)
        item = await service.snooze(
            item_id,
            minutes=minutes,
            telegram_chat_id=telegram_chat_id,
        )
        if item is None:
            await callback.answer("Заявка не найдена.", show_alert=True)
            return
        await _edit_callback_message(
            callback,
            text=f"Заявка GLPI #{item.glpi_ticket_id} отложена на 1 час.",
            reply_markup=build_in_work_keyboard(item.id) if item.status != DONE else None,
        )
        return
    await callback.answer("Неизвестная кнопка.", show_alert=True)


async def _workflow_service(data: dict[str, Any]) -> HelpdeskTicketWorkflowService | None:
    injected = data.get("helpdesk_ticket_service")
    if isinstance(injected, HelpdeskTicketWorkflowService):
        return injected
    session = data.get("db_session")
    if not isinstance(session, AsyncSession):
        return None
    return HelpdeskTicketWorkflowService(HelpdeskTicketWorkItemRepository(session))


async def _is_message_allowed(message: Message, data: dict[str, Any]) -> bool:
    settings = cast(Settings, data["settings"])
    user_id = message.from_user.id if message.from_user else None
    if is_admin_user(user_id, settings.admin_ids):
        return True
    session = data.get("db_session")
    if not isinstance(session, AsyncSession):
        return False
    try:
        access = TelegramAccessService(
            TelegramAccessRepository(session),
            admin_ids=settings.admin_ids,
        )
        if not await access.is_allowed_user(user_id):
            return False
        if message.chat.type in GROUP_CHAT_TYPES:
            return await access.is_allowed_group(message.chat.id)
        return True
    except Exception as exc:
        logger.warning(
            "helpdesk_ticket_access_check_failed",
            extra={"error_type": type(exc).__name__, "chat_type": message.chat.type},
        )
        return False


async def _is_callback_allowed(callback: CallbackQuery, data: dict[str, Any]) -> bool:
    settings = cast(Settings, data["settings"])
    user_id = callback.from_user.id if callback.from_user else None
    if not is_admin_user(user_id, settings.admin_ids):
        session = data.get("db_session")
        if not isinstance(session, AsyncSession):
            return False
        try:
            access = TelegramAccessService(
                TelegramAccessRepository(session),
                admin_ids=settings.admin_ids,
            )
            if not await access.is_allowed_user(user_id):
                return False
            if callback.message is not None and callback.message.chat.type in GROUP_CHAT_TYPES:
                if not await access.is_allowed_group(callback.message.chat.id):
                    return False
        except Exception as exc:
            logger.warning(
                "helpdesk_ticket_callback_access_check_failed",
                extra={"error_type": type(exc).__name__},
            )
            return False
    return await _callback_matches_ticket_chat(callback, data)


async def _callback_matches_ticket_chat(callback: CallbackQuery, data: dict[str, Any]) -> bool:
    service = await _workflow_service(data)
    if service is None:
        return True
    item_id = _item_id_from_callback(callback.data or "")
    if item_id is None:
        return True
    item = await service.repository.get(item_id)
    if item is None:
        return True
    return item.telegram_chat_id == _callback_chat_id(callback, data)


async def _edit_callback_message(
    callback: CallbackQuery,
    *,
    text: str,
    reply_markup: InlineKeyboardMarkup | None,
) -> None:
    if callback.message is None or not hasattr(callback.message, "edit_text"):
        await callback.answer(text)
        return
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=reply_markup)
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc).lower():
            await callback.answer("Уже актуально.", show_alert=False)
            return
        logger.warning(
            "helpdesk_ticket_callback_edit_bad_request",
            extra={"error_type": type(exc).__name__},
        )
        await callback.answer("Не удалось обновить сообщение.", show_alert=True)
        return
    except Exception as exc:
        logger.warning(
            "helpdesk_ticket_callback_edit_failed",
            extra={"error_type": type(exc).__name__},
        )
        await callback.answer("Не удалось обновить сообщение.", show_alert=True)
        return
    await callback.answer()


def _target_helpdesk_chat_id(message: Message, settings: Settings) -> int:
    if getattr(message.chat, "type", "private") == "private":
        configured = _configured_helpdesk_chat_id(settings)
        if configured is not None:
            return configured
        if message.from_user is not None:
            return message.from_user.id
    return int(message.chat.id)


def _callback_chat_id(callback: CallbackQuery, data: dict[str, Any]) -> int:
    settings = cast(Settings, data["settings"])
    if callback.message is not None:
        if getattr(callback.message.chat, "type", "private") == "private":
            configured = _configured_helpdesk_chat_id(settings)
            if configured is not None:
                return configured
        return int(callback.message.chat.id)
    configured = _configured_helpdesk_chat_id(settings)
    return configured or (callback.from_user.id if callback.from_user else 0)


def _configured_helpdesk_chat_id(settings: Settings) -> int | None:
    raw = str(settings.helpdesk_telegram_chat_id or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _item_id_from_callback(callback_data: str) -> str | None:
    parts = callback_data.split(":")
    return parts[2] if len(parts) >= 3 else None


def _minutes_from_callback(parts: list[str]) -> int:
    try:
        value = int(parts[3])
    except (IndexError, ValueError):
        return 60
    return max(1, min(value, 24 * 60))


async def _resolve_bot_username(data: dict[str, Any], fallback: str) -> str:
    bot = data.get("bot")
    if bot is not None:
        try:
            me = await bot.get_me()
        except Exception:
            pass
        else:
            username = getattr(me, "username", None)
            if username:
                return str(username)
    return fallback


def _is_command_for_other_bot(message: Message, bot_username: str) -> bool:
    text = message.text or message.caption
    if not text:
        return False
    command = text.strip().split(maxsplit=1)[0]
    if "@" not in command:
        return False
    target = command.rsplit("@", maxsplit=1)[1].lower()
    own = bot_username.strip().lstrip("@").lower()
    return bool(own) and target != own


def build_router() -> Router:
    router = Router(name="helpdesk_tickets")
    router.message(Command(*HELPDESK_TICKET_COMMANDS))(cmd_ticket)
    router.callback_query(F.data.startswith("hd_ticket:"))(handle_helpdesk_ticket_callback)
    return router


router = build_router()
