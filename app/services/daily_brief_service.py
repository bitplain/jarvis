from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.services.household_memory_service import HouseholdMemoryService
from app.services.reminder_service import ReminderService, ReminderView
from app.services.runtime_settings_service import DEFAULT_LISTS_TIMEZONE
from app.services.shopping_service import ShoppingItemView, ShoppingService

DAILY_BRIEF_SCOPE_TYPES = {"private", "group"}
DEFAULT_DAILY_BRIEF_TIME = "09:00"


@dataclass(frozen=True)
class DailyBriefSettingsInput:
    scope_type: str
    chat_id: int
    user_id: int | None
    enabled: bool = False
    send_time: str = DEFAULT_DAILY_BRIEF_TIME
    timezone: str = DEFAULT_LISTS_TIMEZONE


@dataclass
class StoredDailyBriefSettings:
    id: str
    scope_type: str
    chat_id: int
    user_id: int | None
    enabled: bool
    send_time: str
    timezone: str
    last_sent_date: date | None = None


@dataclass(frozen=True)
class DailyBriefView:
    scope_type: str
    chat_id: int
    timezone: ZoneInfo
    now: datetime
    today_reminders: list[ReminderView]
    overdue_reminders: list[ReminderView]
    shopping_items: list[ShoppingItemView]
    memory_texts: list[str]


class DailyBriefService:
    def __init__(
        self,
        *,
        shopping: ShoppingService,
        reminders: ReminderService,
        household_memory: HouseholdMemoryService,
    ) -> None:
        self.shopping = shopping
        self.reminders = reminders
        self.household_memory = household_memory

    async def build_brief(
        self,
        *,
        scope_type: str,
        chat_id: int,
        user_id: int | None,
        now: datetime,
        timezone: ZoneInfo,
    ) -> DailyBriefView:
        _validate_scope(scope_type)
        local_now = (
            now.astimezone(timezone)
            if now.tzinfo is not None
            else now.replace(tzinfo=timezone)
        )
        reminders = await self.reminders.list_reminders(
            scope_type,
            chat_id,
            user_id if scope_type == "private" else None,
        )
        today_reminders: list[ReminderView] = []
        overdue_reminders: list[ReminderView] = []
        for reminder in reminders:
            local_remind_at = reminder.remind_at.astimezone(timezone)
            if local_remind_at.date() == local_now.date():
                today_reminders.append(reminder)
            elif local_remind_at < datetime.combine(
                local_now.date(),
                datetime.min.time(),
                tzinfo=timezone,
            ):
                overdue_reminders.append(reminder)
        shopping_view = await self.shopping.list_items(scope_type, chat_id)
        memories = await self.household_memory.list_memories(scope_type, chat_id, limit=5)
        return DailyBriefView(
            scope_type=scope_type,
            chat_id=chat_id,
            timezone=timezone,
            now=local_now,
            today_reminders=today_reminders,
            overdue_reminders=overdue_reminders,
            shopping_items=shopping_view.active[:20],
            memory_texts=[memory.text for memory in memories[:5]],
        )


class InMemoryDailyBriefSettingsRepository:
    def __init__(self) -> None:
        self.settings: dict[str, StoredDailyBriefSettings] = {}
        self.scope_index: dict[tuple[str, int, int | None], str] = {}

    async def get_or_create(
        self,
        *,
        scope_type: str,
        chat_id: int,
        user_id: int | None,
    ) -> StoredDailyBriefSettings:
        key = (scope_type, chat_id, user_id)
        existing_id = self.scope_index.get(key)
        if existing_id is not None:
            return self.settings[existing_id]
        return await self.upsert(
            DailyBriefSettingsInput(scope_type=scope_type, chat_id=chat_id, user_id=user_id)
        )

    async def upsert(self, value: DailyBriefSettingsInput) -> StoredDailyBriefSettings:
        _validate_scope(value.scope_type)
        _validate_send_time(value.send_time)
        _validate_timezone(value.timezone)
        key = (value.scope_type, value.chat_id, value.user_id)
        existing_id = self.scope_index.get(key)
        settings_id = existing_id or uuid4().hex
        settings = StoredDailyBriefSettings(
            id=settings_id,
            scope_type=value.scope_type,
            chat_id=value.chat_id,
            user_id=value.user_id,
            enabled=value.enabled,
            send_time=value.send_time,
            timezone=value.timezone,
            last_sent_date=self.settings[settings_id].last_sent_date if existing_id else None,
        )
        self.settings[settings_id] = settings
        self.scope_index[key] = settings_id
        return settings

    async def due_for_delivery(self, now: datetime) -> list[StoredDailyBriefSettings]:
        due: list[StoredDailyBriefSettings] = []
        for settings in self.settings.values():
            if not settings.enabled:
                continue
            timezone = _timezone(settings.timezone)
            local_now = (
                now.astimezone(timezone)
                if now.tzinfo is not None
                else now.replace(tzinfo=timezone)
            )
            today = local_now.date()
            if (
                local_now.strftime("%H:%M") == settings.send_time
                and settings.last_sent_date != today
            ):
                due.append(settings)
        return due

    async def mark_sent_if_due(self, settings_id: str, local_date: str | date) -> bool:
        settings = self.settings.get(settings_id)
        if settings is None:
            return False
        parsed_date = date.fromisoformat(local_date) if isinstance(local_date, str) else local_date
        if settings.last_sent_date == parsed_date:
            return False
        settings.last_sent_date = parsed_date
        return True


def _validate_scope(scope_type: str) -> None:
    if scope_type not in DAILY_BRIEF_SCOPE_TYPES:
        raise ValueError("invalid_daily_brief_scope")


def _validate_send_time(value: str) -> None:
    try:
        hour_text, minute_text = value.split(":", maxsplit=1)
        hour = int(hour_text)
        minute = int(minute_text)
    except ValueError as exc:
        raise ValueError("invalid_daily_brief_time") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59 and len(value) == 5):
        raise ValueError("invalid_daily_brief_time")


def _validate_timezone(value: str) -> None:
    _timezone(value)


def _timezone(value: str) -> ZoneInfo:
    try:
        return ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("invalid_daily_brief_timezone") from exc


def utc_now() -> datetime:
    return datetime.now(UTC)
