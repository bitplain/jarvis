from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, cast
from zoneinfo import ZoneInfo

from aiogram import Router
from aiogram.filters import Filter
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.routers.groups import GROUP_CHAT_TYPES, classify_group_message
from app.db.repositories.daily_brief import DailyBriefSettingsRepository
from app.db.repositories.household_memory import HouseholdMemoryRepository
from app.db.repositories.reminders import ReminderRepository
from app.db.repositories.shopping import ShoppingRepository
from app.services.daily_brief_service import DailyBriefService
from app.services.household_memory_service import HouseholdMemoryService
from app.services.reminder_service import ReminderService
from app.services.runtime_settings_service import DEFAULT_LISTS_TIMEZONE
from app.services.shopping_service import ShoppingService
from app.services.telegram_formatting import format_daily_brief_html

DAILY_BRIEF_COMMANDS = {"сводка", "сводка дня", "что сегодня?"}
logger = logging.getLogger(__name__)


class PrivateDailyBriefFilter(Filter):
    async def __call__(self, message: Message, **data: Any) -> dict[str, Any] | bool:
        del data
        if message.chat.type != "private" or not message.text:
            return False
        if _normalize_command(message.text) not in DAILY_BRIEF_COMMANDS:
            return False
        chat_id = message.from_user.id if message.from_user else message.chat.id
        return {"daily_brief_scope": "private", "daily_brief_chat_id": chat_id}


class GroupDailyBriefFilter(Filter):
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
        if _normalize_command(text) not in DAILY_BRIEF_COMMANDS:
            return False
        return {"daily_brief_scope": "group", "daily_brief_chat_id": message.chat.id}


async def handle_daily_brief_message(
    message: Message,
    daily_brief_scope: str,
    daily_brief_chat_id: int,
    **data: Any,
) -> None:
    if not message.from_user:
        return
    session = cast(AsyncSession | None, data.get("db_session"))
    if session is None:
        await message.answer("Сводка дня временно недоступна: нет подключения к БД.")
        return
    timezone = await _resolve_brief_timezone(
        session,
        daily_brief_scope,
        daily_brief_chat_id,
        message.from_user.id,
    )
    service = DailyBriefService(
        shopping=ShoppingService(ShoppingRepository(session)),
        reminders=ReminderService(ReminderRepository(session)),
        household_memory=HouseholdMemoryService(HouseholdMemoryRepository(session)),
    )
    brief = await service.build_brief(
        scope_type=daily_brief_scope,
        chat_id=daily_brief_chat_id,
        user_id=message.from_user.id if daily_brief_scope == "private" else None,
        now=datetime.now(timezone),
        timezone=timezone,
    )
    await message.answer(format_daily_brief_html(brief), parse_mode="HTML")


async def _resolve_brief_timezone(
    session: AsyncSession,
    scope_type: str,
    chat_id: int,
    user_id: int,
) -> ZoneInfo:
    try:
        settings = await DailyBriefSettingsRepository(session).get_or_create(
            scope_type=scope_type,
            chat_id=chat_id,
            user_id=user_id if scope_type == "private" else None,
        )
        return ZoneInfo(settings.timezone)
    except Exception as exc:
        logger.warning(
            "daily_brief_timezone_unavailable_using_default",
            extra={"error_type": type(exc).__name__},
        )
        return ZoneInfo(DEFAULT_LISTS_TIMEZONE)


def _normalize_command(text: str) -> str:
    return " ".join(text.strip().lower().split())


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


def build_router() -> Router:
    router = Router(name="daily_brief")
    router.message(PrivateDailyBriefFilter())(handle_daily_brief_message)
    router.message(GroupDailyBriefFilter())(handle_daily_brief_message)
    return router


router = build_router()
