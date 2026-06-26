from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, cast

from aiogram import F, Router
from aiogram.filters import Filter, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.middlewares.access import is_admin_user
from app.bot.routers.groups import GROUP_CHAT_TYPES, classify_group_message
from app.db.repositories.reminders import ReminderRepository
from app.db.repositories.runtime_settings import RuntimeSettingRepository
from app.db.repositories.shopping import ShoppingRepository
from app.db.repositories.telegram_access import TelegramAccessRepository
from app.services.reminder_service import ReminderService, ReminderView
from app.services.runtime_settings_service import RuntimeSettingsService, RuntimeSettingsUnavailable
from app.services.shopping_service import ShoppingListView, ShoppingService
from app.services.simple_intent_parser import (
    DEFAULT_TIMEZONE,
    ParserHelpIntent,
    ReminderCreateIntent,
    ReminderListIntent,
    ShoppingAddIntent,
    ShoppingClearDoneIntent,
    ShoppingDeleteIntent,
    ShoppingListIntent,
    parse_explicit_intent,
)
from app.services.telegram_access_service import TelegramAccessService
from app.services.telegram_formatting import (
    format_lists_reminders_group_help_html,
    format_lists_reminders_private_help_html,
    format_reminder_created_html,
    format_reminders_html,
    format_shopping_list_html,
)

logger = logging.getLogger(__name__)
SHOPPING_HELP = (
    "Я понял команду про список, но не понял позицию.\n"
    "Пример: добавь молоко, яйца, сыр в список"
)
REMINDER_HELP = (
    "Я понял команду про напоминание, но не понял время.\n"
    "Примеры:\n"
    "напомни через 30 минут проверить духовку\n"
    "напомни завтра в 10 купить молоко\n"
    "напомни 28.06 в 14:00 оплатить счёт"
)


class ShoppingListInput(StatesGroup):
    add = State()


class ReminderInput(StatesGroup):
    add = State()


class PrivateListsRemindersFilter(Filter):
    async def __call__(self, message: Message, **data: Any) -> dict[str, Any] | bool:
        if message.chat.type != "private" or not message.text:
            return False
        timezone = await _resolve_lists_timezone(data)
        intent = parse_explicit_intent(message.text, timezone=timezone)
        if intent is None:
            return False
        chat_id = message.from_user.id if message.from_user else message.chat.id
        return {
            "lists_reminders_intent": intent,
            "lists_reminders_scope": "private",
            "lists_reminders_chat_id": chat_id,
            "lists_reminders_timezone": timezone,
        }


class GroupListsRemindersFilter(Filter):
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
        text = _strip_group_trigger(message.text, str(bot_username), decision.matched_bot_username)
        timezone = await _resolve_lists_timezone(data)
        intent = parse_explicit_intent(text, timezone=timezone)
        if intent is None:
            return False
        return {
            "lists_reminders_intent": intent,
            "lists_reminders_scope": "group",
            "lists_reminders_chat_id": message.chat.id,
            "lists_reminders_timezone": timezone,
        }


async def handle_lists_reminders_message(
    message: Message,
    lists_reminders_intent: object,
    lists_reminders_scope: str,
    lists_reminders_chat_id: int,
    lists_reminders_timezone: Any = DEFAULT_TIMEZONE,
    **data: Any,
) -> None:
    if not message.from_user:
        return
    session = cast(AsyncSession | None, data.get("db_session"))
    if session is None:
        await message.answer("База данных временно недоступна.")
        return
    if isinstance(lists_reminders_intent, ParserHelpIntent):
        if lists_reminders_scope == "group":
            bot_username = await _resolve_bot_username(data)
            await message.answer(
                format_lists_reminders_group_help_html(bot_username),
                parse_mode="HTML",
            )
        else:
            await message.answer(format_lists_reminders_private_help_html(), parse_mode="HTML")
        return
    shopping = ShoppingService(ShoppingRepository(session))
    reminders = ReminderService(ReminderRepository(session))
    user_id = message.from_user.id
    if isinstance(lists_reminders_intent, ShoppingAddIntent):
        view = await shopping.add_items(
            lists_reminders_scope,
            lists_reminders_chat_id,
            user_id,
            lists_reminders_intent.items,
        )
        await _answer_shopping(message, view)
        return
    if isinstance(lists_reminders_intent, ShoppingListIntent):
        view = await shopping.list_items(lists_reminders_scope, lists_reminders_chat_id)
        await _answer_shopping(message, view)
        return
    if isinstance(lists_reminders_intent, ShoppingDeleteIntent):
        deleted_view = await shopping.delete_exact_text(
            lists_reminders_scope,
            lists_reminders_chat_id,
            lists_reminders_intent.query,
            user_id,
        )
        if deleted_view is None:
            await message.answer("Не нашёл точное совпадение в активном списке.")
            return
        await _answer_shopping(message, deleted_view)
        return
    if isinstance(lists_reminders_intent, ShoppingClearDoneIntent):
        view = await shopping.clear_done(lists_reminders_scope, lists_reminders_chat_id, user_id)
        await _answer_shopping(message, view)
        return
    if isinstance(lists_reminders_intent, ReminderCreateIntent):
        now = datetime.now(lists_reminders_intent.remind_at.tzinfo)
        if lists_reminders_intent.remind_at <= now:
            await message.answer("Время напоминания уже прошло.")
            return
        reminder = await reminders.create_reminder(
            lists_reminders_scope,
            lists_reminders_chat_id,
            user_id,
            lists_reminders_intent.text,
            lists_reminders_intent.remind_at,
        )
        await message.answer(
            format_reminder_created_html(reminder, timezone=lists_reminders_timezone),
            parse_mode="HTML",
            reply_markup=build_reminder_keyboard(reminder),
        )
        return
    if isinstance(lists_reminders_intent, ReminderListIntent):
        reminder_views = await reminders.list_reminders(
            lists_reminders_scope,
            lists_reminders_chat_id,
            user_id if lists_reminders_scope == "private" else None,
        )
        await message.answer(
            format_reminders_html(reminder_views, timezone=lists_reminders_timezone),
            parse_mode="HTML",
            reply_markup=build_reminders_list_keyboard(reminder_views),
        )


async def handle_lists_reminders_callback(callback: CallbackQuery, **data: Any) -> None:
    callback_data = callback.data or ""
    session = cast(AsyncSession | None, data.get("db_session"))
    if session is None:
        await callback.answer("База данных временно недоступна.", show_alert=True)
        return
    if not await _is_callback_allowed(callback, session, data):
        if callback.message is not None and callback.message.chat.type in GROUP_CHAT_TYPES:
            await callback.answer()
        else:
            await callback.answer("Доступ запрещён.", show_alert=True)
        return
    user_id = callback.from_user.id
    if callback_data.startswith("shop:"):
        await _handle_shopping_callback(callback, session, callback_data, user_id, data)
        return
    if callback_data.startswith("rem:"):
        await _handle_reminder_callback(callback, session, callback_data, user_id, data)


async def _handle_shopping_callback(
    callback: CallbackQuery,
    session: AsyncSession,
    callback_data: str,
    user_id: int,
    data: dict[str, Any],
) -> None:
    service = ShoppingService(ShoppingRepository(session))
    parts = callback_data.split(":")
    if callback_data == "shop:add" and callback.message is not None:
        state = cast(FSMContext | None, data.get("state"))
        if state is None:
            await callback.answer("FSM временно недоступен.", show_alert=True)
            return
        scope, chat_id = _callback_scope_chat(callback)
        await state.set_state(ShoppingListInput.add)
        await state.update_data(shopping_scope=scope, shopping_chat_id=chat_id)
        edited = await _edit_callback_message(
            callback,
            text=(
                "Что добавить в список покупок?\n"
                "Можно несколько позиций через запятую.\n"
                "Для отмены отправьте /cancel."
            ),
            reply_markup=None,
        )
        if not edited:
            await callback.answer()
        return
    if callback_data == "shop:clear_all" and callback.message is not None:
        await _edit_callback_message(
            callback,
            text="Точно очистить весь список покупок?",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Да, очистить",
                            callback_data="shop:clear_all_confirm",
                        ),
                        InlineKeyboardButton(text="Отмена", callback_data="shop:clear_all_cancel"),
                    ]
                ]
            ),
        )
        return
    if callback_data == "shop:clear_all_confirm" and callback.message is not None:
        scope, chat_id = _callback_scope_chat(callback)
        view = await service.clear_all(scope, chat_id, user_id)
        await _edit_callback_message(
            callback,
            text=format_shopping_list_html(view),
            reply_markup=build_shopping_keyboard(view),
        )
        return
    if callback_data == "shop:clear_all_cancel" and callback.message is not None:
        scope, chat_id = _callback_scope_chat(callback)
        view = await service.list_items(scope, chat_id)
        await _edit_callback_message(
            callback,
            text=format_shopping_list_html(view),
            reply_markup=build_shopping_keyboard(view),
        )
        return
    if len(parts) < 3:
        await callback.answer("Неизвестная кнопка.", show_alert=True)
        return
    action, token = parts[1], parts[2]
    if action == "done":
        view = await service.mark_done(token, user_id)
    elif action == "restore":
        view = await service.restore_item(token, user_id)
    elif action == "del":
        view = await service.delete_item(token, user_id)
    elif action == "clear_done" and callback.message is not None:
        scope = "group" if callback.message.chat.type in GROUP_CHAT_TYPES else "private"
        chat_id = callback.message.chat.id
        view = await service.clear_done(scope, chat_id, user_id)
    else:
        await callback.answer("Неизвестная кнопка.", show_alert=True)
        return
    await _edit_callback_message(
        callback,
        text=format_shopping_list_html(view),
        reply_markup=build_shopping_keyboard(view),
    )


async def _handle_reminder_callback(
    callback: CallbackQuery,
    session: AsyncSession,
    callback_data: str,
    user_id: int,
    data: dict[str, Any],
) -> None:
    service = ReminderService(ReminderRepository(session))
    timezone = await _resolve_lists_timezone(data)
    parts = callback_data.split(":")
    if callback_data == "rem:add" and callback.message is not None:
        state = cast(FSMContext | None, data.get("state"))
        if state is None:
            await callback.answer("FSM временно недоступен.", show_alert=True)
            return
        scope, chat_id = _callback_scope_chat(callback)
        await state.set_state(ReminderInput.add)
        await state.update_data(reminder_scope=scope, reminder_chat_id=chat_id)
        edited = await _edit_callback_message(
            callback,
            text=(
                "Что напомнить и когда?\n\n"
                "Примеры:\n"
                "напомни через 30 минут проверить духовку\n"
                "напомни завтра в 10 купить молоко\n\n"
                "Для отмены отправьте /cancel."
            ),
            reply_markup=None,
        )
        if not edited:
            await callback.answer()
        return
    if len(parts) < 3:
        await callback.answer("Неизвестная кнопка.", show_alert=True)
        return
    action, token = parts[1], parts[2]
    if action in {"done", "del"}:
        reminders = await service.cancel_reminder(token, user_id)
        await _edit_callback_message(
            callback,
            text=format_reminders_html(reminders, timezone=timezone),
            reply_markup=build_reminders_list_keyboard(reminders),
        )
        return
    try:
        if action == "snooze10":
            reminder = await service.snooze_reminder(token, timedelta(minutes=10), user_id)
        elif action == "snooze60":
            reminder = await service.snooze_reminder(token, timedelta(hours=1), user_id)
        else:
            await callback.answer("Неизвестная кнопка.", show_alert=True)
            return
    except ValueError:
        await _edit_callback_message(
            callback,
            text=format_reminders_html([], timezone=timezone),
            reply_markup=build_reminders_list_keyboard([]),
        )
        return
    await _edit_callback_message(
        callback,
        text=format_reminder_created_html(reminder, timezone=timezone),
        reply_markup=build_reminder_keyboard(reminder),
    )


def build_shopping_keyboard(view: ShoppingListView) -> InlineKeyboardMarkup | None:
    rows: list[list[InlineKeyboardButton]] = []
    for item in view.active:
        token = _short(item.id)
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"✅ {_button_text(item.text)}",
                    callback_data=f"shop:done:{token}",
                ),
                InlineKeyboardButton(text="🗑", callback_data=f"shop:del:{token}"),
            ]
        )
    for item in view.done:
        token = _short(item.id)
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"↩️ {_button_text(item.text)}",
                    callback_data=f"shop:restore:{token}",
                ),
                InlineKeyboardButton(text="🗑", callback_data=f"shop:del:{token}"),
            ]
        )
    if view.done:
        rows.append(
            [
                InlineKeyboardButton(
                    text="✅ Очистить купленное",
                    callback_data="shop:clear_done:done",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="➕ Добавить", callback_data="shop:add")])
    if view.active or view.done:
        rows.append([InlineKeyboardButton(text="🧹 Очистить всё", callback_data="shop:clear_all")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_reminder_keyboard(reminder: ReminderView) -> InlineKeyboardMarkup:
    token = _short(reminder.id)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Выполнено", callback_data=f"rem:done:{token}"),
                InlineKeyboardButton(text="🗑 Удалить", callback_data=f"rem:del:{token}"),
            ],
            [
                InlineKeyboardButton(text="⏰ +10 мин", callback_data=f"rem:snooze10:{token}"),
                InlineKeyboardButton(text="⏰ +1 час", callback_data=f"rem:snooze60:{token}"),
            ],
        ]
    )


def build_reminders_list_keyboard(reminders: list[ReminderView]) -> InlineKeyboardMarkup | None:
    rows: list[list[InlineKeyboardButton]] = []
    for reminder in reminders:
        token = _short(reminder.id)
        rows.append(
            [
                InlineKeyboardButton(text="✅ Выполнено", callback_data=f"rem:done:{token}"),
                InlineKeyboardButton(text="⏰ +10 мин", callback_data=f"rem:snooze10:{token}"),
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(text="⏰ +1 час", callback_data=f"rem:snooze60:{token}"),
                InlineKeyboardButton(text="🗑 Удалить", callback_data=f"rem:del:{token}"),
            ]
        )
    rows.append([InlineKeyboardButton(text="➕ Добавить напоминание", callback_data="rem:add")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _answer_shopping(message: Message, view: ShoppingListView) -> None:
    await message.answer(
        format_shopping_list_html(view),
        parse_mode="HTML",
        reply_markup=build_shopping_keyboard(view),
    )


async def _edit_callback_message(
    callback: CallbackQuery,
    *,
    text: str,
    reply_markup: InlineKeyboardMarkup | None,
) -> bool:
    if callback.message is None or not hasattr(callback.message, "edit_text"):
        await callback.answer()
        return False
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=reply_markup)
    except Exception as exc:
        if "message is not modified" in str(exc).lower():
            await callback.answer("Уже актуально.", show_alert=False)
            return False
        logger.warning(
            "lists_reminders_callback_edit_failed",
            extra={"error_type": type(exc).__name__},
        )
        await callback.answer("Не удалось обновить сообщение.", show_alert=True)
        return False
    await callback.answer()
    return True


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


def _strip_group_trigger(text: str, bot_username: str, matched_username: bool) -> str:
    if not matched_username:
        return text.strip()
    username = bot_username.strip().lstrip("@")
    if not username:
        return text.strip()
    return (
        text.replace(f"@{username}", "")
        .replace(f"@{username.lower()}", "")
        .replace(f"@{username.upper()}", "")
        .strip()
    )


def _short(identifier: str) -> str:
    return identifier.replace("-", "")[:8]


def _button_text(text: str) -> str:
    return text if len(text) <= 24 else text[:23] + "…"


async def handle_shopping_input_message(
    message: Message,
    state: FSMContext,
    **data: Any,
) -> None:
    if not message.from_user:
        await state.clear()
        return
    text = (message.text or message.caption or "").strip()
    if text.lower() == "/cancel":
        await state.clear()
        await message.answer("Ввод отменён.")
        return
    session = cast(AsyncSession | None, data.get("db_session"))
    if session is None:
        await message.answer("База данных временно недоступна.")
        return
    state_data = await state.get_data()
    scope = str(state_data.get("shopping_scope") or _message_scope(message))
    chat_id = int(state_data.get("shopping_chat_id") or message.chat.id)
    intent = parse_explicit_intent(f"добавь {text} в список")
    if not isinstance(intent, ShoppingAddIntent):
        await message.answer(
            "Не понял, что добавить.\n\n"
            "Что добавить в список покупок?\n"
            "Можно несколько позиций через запятую.\n"
            "Для отмены отправьте /cancel."
        )
        return
    view = await ShoppingService(ShoppingRepository(session)).add_items(
        scope,
        chat_id,
        message.from_user.id,
        intent.items,
    )
    await state.clear()
    await _answer_shopping(message, view)


async def handle_reminder_input_message(
    message: Message,
    state: FSMContext,
    **data: Any,
) -> None:
    if not message.from_user:
        await state.clear()
        return
    text = (message.text or message.caption or "").strip()
    if text.lower() == "/cancel":
        await state.clear()
        await message.answer("Ввод отменён.")
        return
    session = cast(AsyncSession | None, data.get("db_session"))
    if session is None:
        await message.answer("База данных временно недоступна.")
        return
    state_data = await state.get_data()
    scope = str(state_data.get("reminder_scope") or _message_scope(message))
    chat_id = int(state_data.get("reminder_chat_id") or message.chat.id)
    timezone = await _resolve_lists_timezone(data)
    command_text = text if text.lower().startswith("напомни ") else f"напомни {text}"
    intent = parse_explicit_intent(command_text, timezone=timezone)
    if not isinstance(intent, ReminderCreateIntent):
        await message.answer(
            "Не понял напоминание.\n\n"
            "Примеры:\n"
            "напомни через 30 минут проверить духовку\n"
            "напомни завтра в 10 купить молоко\n\n"
            "Для отмены отправьте /cancel."
        )
        return
    now = datetime.now(intent.remind_at.tzinfo)
    if intent.remind_at <= now:
        await message.answer("Время напоминания уже прошло.")
        return
    reminder = await ReminderService(ReminderRepository(session)).create_reminder(
        scope,
        chat_id,
        message.from_user.id,
        intent.text,
        intent.remind_at,
    )
    await state.clear()
    reminder_views = await ReminderService(ReminderRepository(session)).list_reminders(
        scope,
        chat_id,
        message.from_user.id if scope == "private" else None,
    )
    await message.answer(
        format_reminder_created_html(reminder, timezone=timezone),
        parse_mode="HTML",
        reply_markup=build_reminder_keyboard(reminder),
    )
    await message.answer(
        format_reminders_html(reminder_views, timezone=timezone),
        parse_mode="HTML",
        reply_markup=build_reminders_list_keyboard(reminder_views),
    )


async def _resolve_lists_timezone(data: dict[str, Any]) -> Any:
    session = data.get("db_session")
    if session is None:
        return DEFAULT_TIMEZONE
    try:
        return await RuntimeSettingsService(
            RuntimeSettingRepository(session)
        ).get_lists_timezone()
    except RuntimeSettingsUnavailable:
        return DEFAULT_TIMEZONE
    except Exception as exc:
        logger.warning(
            "lists_timezone_unavailable_using_default",
            extra={"error_type": type(exc).__name__},
        )
        return DEFAULT_TIMEZONE


async def _resolve_bot_username(data: dict[str, Any]) -> str:
    settings = data.get("settings")
    fallback = getattr(settings, "telegram_bot_username", "")
    bot = data.get("bot")
    if bot is not None:
        try:
            me = await bot.get_me()
        except Exception:
            return str(fallback)
        username = getattr(me, "username", None)
        if username:
            return str(username)
    return str(fallback)


def _callback_scope_chat(callback: CallbackQuery) -> tuple[str, int]:
    if callback.message is None:
        return "private", callback.from_user.id
    scope = "group" if callback.message.chat.type in GROUP_CHAT_TYPES else "private"
    chat_id = callback.message.chat.id
    if scope == "private":
        chat_id = callback.from_user.id
    return scope, chat_id


def _message_scope(message: Message) -> str:
    return "group" if message.chat.type in GROUP_CHAT_TYPES else "private"


def build_router() -> Router:
    router = Router(name="lists_reminders")
    router.message(StateFilter(ShoppingListInput.add))(handle_shopping_input_message)
    router.message(StateFilter(ReminderInput.add))(handle_reminder_input_message)
    router.message(PrivateListsRemindersFilter())(handle_lists_reminders_message)
    router.message(GroupListsRemindersFilter())(handle_lists_reminders_message)
    router.callback_query(F.data.startswith("shop:") | F.data.startswith("rem:"))(
        handle_lists_reminders_callback
    )
    return router


router = build_router()
