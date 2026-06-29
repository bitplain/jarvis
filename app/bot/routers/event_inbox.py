from __future__ import annotations

import logging
from typing import Any, cast

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.middlewares.access import GROUP_CHAT_TYPES, is_admin_user
from app.core.config import Settings
from app.db.repositories.event_items import EventItemRepository
from app.db.repositories.telegram_access import TelegramAccessRepository
from app.services.event_cards import (
    ALLOWED_EVENT_ACTION_IDS,
    EVENT_CALLBACK_PREFIX,
    render_card_buttons,
    render_card_to_telegram_text,
)
from app.services.event_items import EventItemService, StoredEventItem
from app.services.telegram_access_service import TelegramAccessService

logger = logging.getLogger(__name__)
EVENT_INBOX_LIMIT = 10


def build_router() -> Router:
    router = Router(name="event_inbox")
    router.message.register(cmd_inbox, Command("inbox"))
    router.message.register(cmd_work, Command("work"))
    router.callback_query.register(
        handle_event_callback,
        F.data.startswith(f"{EVENT_CALLBACK_PREFIX}:"),
    )
    return router


async def cmd_inbox(message: Message, **data: Any) -> None:
    service = await _event_service(data)
    if service is None:
        await message.answer("База данных временно недоступна.")
        return
    user_id = _message_user_id(message)
    if user_id is None:
        await message.answer("Не удалось определить пользователя.")
        return
    items = await service.list_for_inbox(
        user_id=user_id,
        chat_id=message.chat.id,
        limit=EVENT_INBOX_LIMIT,
    )
    await _answer_event_items(
        message,
        items,
        empty_text="В личном inbox пока нет активных событий.",
    )


async def cmd_work(message: Message, **data: Any) -> None:
    service = await _event_service(data)
    if service is None:
        await message.answer("База данных временно недоступна.")
        return
    user_id = _message_user_id(message)
    if user_id is None:
        await message.answer("Не удалось определить пользователя.")
        return
    items = await service.list_for_work(
        user_id=user_id,
        chat_id=message.chat.id,
        limit=EVENT_INBOX_LIMIT,
    )
    await _answer_event_items(
        message,
        items,
        empty_text="В рабочем inbox пока нет активных событий.",
    )


async def handle_event_callback(callback: CallbackQuery, **data: Any) -> None:
    callback_data = callback.data or ""
    parsed = _parse_event_callback_data(callback_data)
    if parsed is None:
        await callback.answer("Неизвестная кнопка.", show_alert=True)
        return
    action, event_id = parsed
    service = await _event_service(data)
    if service is None:
        await callback.answer("База данных временно недоступна.", show_alert=True)
        return
    item = await service.get_event(event_id)
    if item is None:
        await callback.answer("Событие не найдено.", show_alert=True)
        return
    if not await _is_callback_allowed(callback, item, data):
        await callback.answer("Доступ запрещён.", show_alert=True)
        return
    if action == "done":
        updated = await service.mark_done(event_id)
        if updated is None:
            await callback.answer("Событие не найдено.", show_alert=True)
            return
        await callback.answer("Готово.", show_alert=False)
        return
    if action == "snooze":
        updated = await service.snooze_event(event_id)
        if updated is None:
            await callback.answer("Событие не найдено.", show_alert=True)
            return
        await callback.answer("Отложил.", show_alert=False)
        return
    if action == "details":
        if callback.message is not None and hasattr(callback.message, "answer"):
            await callback.message.answer(
                render_card_to_telegram_text(
                    item.card_json,
                    fallback_title=item.title,
                    fallback_body=item.body,
                ),
                parse_mode="HTML",
                reply_markup=render_card_buttons(item.id, item.card_json),
            )
        await callback.answer()
        return
    await callback.answer("Неизвестная кнопка.", show_alert=True)


async def _answer_event_items(
    message: Message,
    items: list[StoredEventItem],
    *,
    empty_text: str,
) -> None:
    if not items:
        await message.answer(empty_text)
        return
    for item in items:
        await message.answer(
            render_card_to_telegram_text(
                item.card_json,
                fallback_title=item.title,
                fallback_body=item.body,
            ),
            parse_mode="HTML",
            reply_markup=render_card_buttons(item.id, item.card_json),
        )


async def _event_service(data: dict[str, Any]) -> EventItemService | None:
    injected = data.get("event_item_service")
    if isinstance(injected, EventItemService):
        return injected
    session = data.get("db_session")
    if not isinstance(session, AsyncSession):
        return None
    return EventItemService(EventItemRepository(session))


async def _is_callback_allowed(
    callback: CallbackQuery,
    item: StoredEventItem,
    data: dict[str, Any],
) -> bool:
    settings = cast(Settings, data["settings"])
    user_id = callback.from_user.id if callback.from_user else None
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
        if callback.message is not None and callback.message.chat.type in GROUP_CHAT_TYPES:
            if not await access.is_allowed_group(callback.message.chat.id):
                return False
    except Exception as exc:
        logger.warning(
            "event_inbox_callback_access_check_failed",
            extra={"error_type": type(exc).__name__},
        )
        return False
    if item.user_id == user_id:
        return True
    return callback.message is not None and item.chat_id == callback.message.chat.id


def _parse_event_callback_data(callback_data: str) -> tuple[str, str] | None:
    parts = callback_data.split(":")
    if len(parts) != 3 or parts[0] != EVENT_CALLBACK_PREFIX:
        return None
    action = parts[1].strip().lower()
    event_id = parts[2].strip().lower()
    if action not in ALLOWED_EVENT_ACTION_IDS:
        return None
    if len(event_id) != 32:
        return None
    return action, event_id


def _message_user_id(message: Message) -> int | None:
    return message.from_user.id if message.from_user else None
