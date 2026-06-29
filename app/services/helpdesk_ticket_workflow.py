from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from html import escape
from typing import Protocol
from uuid import uuid4
from zoneinfo import ZoneInfo

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

WAITING_ACK = "waiting_ack"
IN_WORK = "in_work"
DONE = "done"
DISMISSED = "dismissed"
ACTIVE_STATUSES = {WAITING_ACK, IN_WORK}
WAITING_ACK_INTERVAL_MINUTES = 10
IN_WORK_INTERVAL_MINUTES = 30
MOSCOW_TZ = ZoneInfo("Europe/Moscow")


@dataclass
class StoredHelpdeskTicketWorkItem:
    id: str
    glpi_ticket_id: str
    latest_event_id: str | None
    title: str
    status: str
    telegram_chat_id: int
    assigned_by_user_id: int | None
    assigned_at: datetime | None
    done_at: datetime | None
    next_reminder_at: datetime | None
    last_reminded_at: datetime | None
    reminder_interval_minutes: int
    created_at: datetime
    updated_at: datetime


class HelpdeskTicketWorkItemRepositoryProtocol(Protocol):
    async def upsert_waiting_ack(
        self,
        *,
        glpi_ticket_id: str,
        latest_event_id: str | None,
        title: str,
        telegram_chat_id: int,
        now: datetime,
    ) -> StoredHelpdeskTicketWorkItem: ...

    async def get(self, item_id: str) -> StoredHelpdeskTicketWorkItem | None: ...

    async def list_in_work(
        self,
        *,
        telegram_chat_id: int,
    ) -> list[StoredHelpdeskTicketWorkItem]: ...

    async def take(
        self,
        item_id: str,
        *,
        actor_user_id: int,
        telegram_chat_id: int,
        now: datetime,
    ) -> StoredHelpdeskTicketWorkItem | None: ...

    async def mark_done(
        self,
        item_id: str,
        *,
        actor_user_id: int,
        telegram_chat_id: int,
        now: datetime,
    ) -> StoredHelpdeskTicketWorkItem | None: ...

    async def snooze(
        self,
        item_id: str,
        *,
        minutes: int,
        telegram_chat_id: int,
        now: datetime,
    ) -> StoredHelpdeskTicketWorkItem | None: ...

    async def due_reminders(
        self,
        now: datetime,
        *,
        limit: int,
    ) -> list[StoredHelpdeskTicketWorkItem]: ...

    async def mark_reminded(
        self,
        item_id: str,
        *,
        now: datetime,
    ) -> StoredHelpdeskTicketWorkItem | None: ...

    async def reschedule_active_reminders_after(
        self,
        *,
        now: datetime,
    ) -> int: ...


class HelpdeskTicketWorkflowService:
    def __init__(
        self,
        repository: HelpdeskTicketWorkItemRepositoryProtocol,
        *,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.now_factory = now_factory or (lambda: datetime.now(UTC))

    async def create_or_update_waiting_ack(
        self,
        *,
        glpi_ticket_id: str,
        latest_event_id: str | None,
        title: str,
        telegram_chat_id: int,
    ) -> StoredHelpdeskTicketWorkItem:
        return await self.repository.upsert_waiting_ack(
            glpi_ticket_id=_normalize_ticket_id(glpi_ticket_id),
            latest_event_id=latest_event_id,
            title=_normalize_title(title),
            telegram_chat_id=telegram_chat_id,
            now=_to_utc(self.now_factory()),
        )

    async def list_in_work(
        self,
        *,
        telegram_chat_id: int,
    ) -> list[StoredHelpdeskTicketWorkItem]:
        return await self.repository.list_in_work(telegram_chat_id=telegram_chat_id)

    async def take(
        self,
        item_id: str,
        *,
        actor_user_id: int,
        telegram_chat_id: int,
    ) -> StoredHelpdeskTicketWorkItem | None:
        return await self.repository.take(
            item_id,
            actor_user_id=actor_user_id,
            telegram_chat_id=telegram_chat_id,
            now=_to_utc(self.now_factory()),
        )

    async def mark_done(
        self,
        item_id: str,
        *,
        actor_user_id: int,
        telegram_chat_id: int,
    ) -> StoredHelpdeskTicketWorkItem | None:
        return await self.repository.mark_done(
            item_id,
            actor_user_id=actor_user_id,
            telegram_chat_id=telegram_chat_id,
            now=_to_utc(self.now_factory()),
        )

    async def snooze(
        self,
        item_id: str,
        *,
        minutes: int,
        telegram_chat_id: int,
    ) -> StoredHelpdeskTicketWorkItem | None:
        return await self.repository.snooze(
            item_id,
            minutes=minutes,
            telegram_chat_id=telegram_chat_id,
            now=_to_utc(self.now_factory()),
        )

    async def due_reminders(
        self,
        now: datetime,
        *,
        limit: int = 50,
    ) -> list[StoredHelpdeskTicketWorkItem]:
        return await self.repository.due_reminders(_to_utc(now), limit=limit)

    async def mark_reminded(
        self,
        item_id: str,
        *,
        now: datetime | None = None,
    ) -> StoredHelpdeskTicketWorkItem | None:
        return await self.repository.mark_reminded(
            item_id,
            now=_to_utc(now or self.now_factory()),
        )

    async def reschedule_active_reminders_after_vacation(
        self,
        *,
        now: datetime | None = None,
    ) -> int:
        return await self.repository.reschedule_active_reminders_after(
            now=_to_utc(now or self.now_factory()),
        )


class InMemoryHelpdeskTicketWorkItemRepository:
    def __init__(self) -> None:
        self.items: dict[str, StoredHelpdeskTicketWorkItem] = {}

    async def upsert_waiting_ack(
        self,
        *,
        glpi_ticket_id: str,
        latest_event_id: str | None,
        title: str,
        telegram_chat_id: int,
        now: datetime,
    ) -> StoredHelpdeskTicketWorkItem:
        existing = self._by_ticket_chat(glpi_ticket_id, telegram_chat_id)
        if existing is None:
            item = StoredHelpdeskTicketWorkItem(
                id=uuid4().hex,
                glpi_ticket_id=glpi_ticket_id,
                latest_event_id=latest_event_id,
                title=title,
                status=WAITING_ACK,
                telegram_chat_id=telegram_chat_id,
                assigned_by_user_id=None,
                assigned_at=None,
                done_at=None,
                next_reminder_at=now + timedelta(minutes=WAITING_ACK_INTERVAL_MINUTES),
                last_reminded_at=None,
                reminder_interval_minutes=WAITING_ACK_INTERVAL_MINUTES,
                created_at=now,
                updated_at=now,
            )
            self.items[item.id] = item
            return replace(item)
        existing.latest_event_id = latest_event_id
        existing.title = title
        existing.updated_at = now
        if existing.status == WAITING_ACK:
            existing.reminder_interval_minutes = WAITING_ACK_INTERVAL_MINUTES
            if existing.next_reminder_at is None:
                existing.next_reminder_at = now + timedelta(minutes=WAITING_ACK_INTERVAL_MINUTES)
        return replace(existing)

    async def get(self, item_id: str) -> StoredHelpdeskTicketWorkItem | None:
        item = self.items.get(_resolve_id(item_id, self.items))
        return replace(item) if item is not None else None

    async def list_in_work(self, *, telegram_chat_id: int) -> list[StoredHelpdeskTicketWorkItem]:
        sorted_items = sorted(
            [
                item
                for item in self.items.values()
                if item.telegram_chat_id == telegram_chat_id and item.status == IN_WORK
            ],
            key=lambda item: item.assigned_at or item.updated_at,
        )
        return [replace(item) for item in sorted_items]

    async def take(
        self,
        item_id: str,
        *,
        actor_user_id: int,
        telegram_chat_id: int,
        now: datetime,
    ) -> StoredHelpdeskTicketWorkItem | None:
        item = self._get_ref(item_id)
        if (
            item is None
            or item.telegram_chat_id != telegram_chat_id
            or item.status in {DONE, DISMISSED}
        ):
            if item is not None and item.telegram_chat_id == telegram_chat_id:
                return replace(item)
            return None
        item.status = IN_WORK
        item.assigned_by_user_id = actor_user_id
        item.assigned_at = item.assigned_at or now
        item.reminder_interval_minutes = IN_WORK_INTERVAL_MINUTES
        item.next_reminder_at = now + timedelta(minutes=IN_WORK_INTERVAL_MINUTES)
        item.updated_at = now
        return replace(item)

    async def mark_done(
        self,
        item_id: str,
        *,
        actor_user_id: int,
        telegram_chat_id: int,
        now: datetime,
    ) -> StoredHelpdeskTicketWorkItem | None:
        del actor_user_id
        item = self._get_ref(item_id)
        if item is None or item.telegram_chat_id != telegram_chat_id:
            return None
        item.status = DONE
        item.done_at = item.done_at or now
        item.next_reminder_at = None
        item.updated_at = now
        return replace(item)

    async def snooze(
        self,
        item_id: str,
        *,
        minutes: int,
        telegram_chat_id: int,
        now: datetime,
    ) -> StoredHelpdeskTicketWorkItem | None:
        item = self._get_ref(item_id)
        if (
            item is None
            or item.telegram_chat_id != telegram_chat_id
            or item.status not in ACTIVE_STATUSES
        ):
            return None
        item.next_reminder_at = now + timedelta(minutes=minutes)
        item.updated_at = now
        return replace(item)

    async def due_reminders(
        self,
        now: datetime,
        *,
        limit: int,
    ) -> list[StoredHelpdeskTicketWorkItem]:
        due_items = sorted(
            [
                item
                for item in self.items.values()
                if item.status in ACTIVE_STATUSES
                and item.next_reminder_at is not None
                and item.next_reminder_at <= now
            ],
            key=lambda item: item.next_reminder_at or item.updated_at,
        )[:limit]
        return [replace(item) for item in due_items]

    async def mark_reminded(
        self,
        item_id: str,
        *,
        now: datetime,
    ) -> StoredHelpdeskTicketWorkItem | None:
        item = self._get_ref(item_id)
        if item is None or item.status not in ACTIVE_STATUSES:
            return None
        item.last_reminded_at = now
        item.next_reminder_at = now + timedelta(minutes=item.reminder_interval_minutes)
        item.updated_at = now
        return replace(item)

    async def reschedule_active_reminders_after(
        self,
        *,
        now: datetime,
    ) -> int:
        updated = 0
        for item in self.items.values():
            if item.status not in ACTIVE_STATUSES:
                continue
            item.next_reminder_at = now + timedelta(minutes=item.reminder_interval_minutes)
            item.updated_at = now
            updated += 1
        return updated

    def _by_ticket_chat(
        self,
        glpi_ticket_id: str,
        telegram_chat_id: int,
    ) -> StoredHelpdeskTicketWorkItem | None:
        for item in self.items.values():
            if item.glpi_ticket_id == glpi_ticket_id and item.telegram_chat_id == telegram_chat_id:
                return item
        return None

    def _get_ref(self, item_id: str) -> StoredHelpdeskTicketWorkItem | None:
        return self.items.get(_resolve_id(item_id, self.items))


def build_waiting_ack_keyboard(item_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="В работу", callback_data=f"hd_ticket:take:{item_id}")]
        ]
    )


def build_in_work_keyboard(item_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Готово", callback_data=f"hd_ticket:done:{item_id}"),
                InlineKeyboardButton(
                    text="Отложить 1ч",
                    callback_data=f"hd_ticket:snooze:{item_id}:60",
                ),
            ]
        ]
    )


def build_ticket_list_keyboard(
    items: list[StoredHelpdeskTicketWorkItem],
) -> InlineKeyboardMarkup | None:
    rows: list[list[InlineKeyboardButton]] = []
    for item in items:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Готово",
                    callback_data=f"hd_ticket:done:{_short(item.id)}",
                ),
                InlineKeyboardButton(
                    text="Отложить 1ч",
                    callback_data=f"hd_ticket:snooze:{_short(item.id)}:60",
                ),
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def format_helpdesk_ticket_reminder_html(item: StoredHelpdeskTicketWorkItem) -> str:
    if item.status == WAITING_ACK:
        text = f"Новая заявка GLPI #{escape(item.glpi_ticket_id)} ещё не взята в работу."
    else:
        text = f"Заявка GLPI #{escape(item.glpi_ticket_id)} всё ещё в работе."
    title = escape(item.title)
    return f"{text}\n\n<blockquote>{title}</blockquote>"


def format_helpdesk_in_work_list_html(items: list[StoredHelpdeskTicketWorkItem]) -> str:
    if not items:
        return "Заявок в работе нет."
    lines = ["<b>Заявки в работе</b>", ""]
    for index, item in enumerate(items, start=1):
        lines.append(f"{index}. <b>GLPI #{escape(item.glpi_ticket_id)}</b>")
        lines.append(escape(item.title))
        assigned_at = _format_dt(item.assigned_at)
        next_reminder = _format_dt(item.next_reminder_at)
        lines.append(f"В работе с: {escape(assigned_at)}")
        lines.append(f"Следующее напоминание: {escape(next_reminder)}")
        if index != len(items):
            lines.append("")
    return "\n".join(lines)


def _format_dt(value: datetime | None) -> str:
    if value is None:
        return "не задано"
    local = (
        value.astimezone(MOSCOW_TZ)
        if value.tzinfo
        else value.replace(tzinfo=UTC).astimezone(MOSCOW_TZ)
    )
    return local.strftime("%d.%m.%Y %H:%M МСК")


def _normalize_ticket_id(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("empty_glpi_ticket_id")
    return normalized


def _normalize_title(value: str) -> str:
    normalized = " ".join(value.strip().split())
    return normalized[:1000] or "Без темы"


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _resolve_id(item_id: str, items: dict[str, StoredHelpdeskTicketWorkItem]) -> str:
    if item_id in items:
        return item_id
    compact = item_id.replace("-", "")
    for key in items:
        if key.replace("-", "").startswith(compact):
            return key
    return item_id


def _short(value: str) -> str:
    return value.replace("-", "")[:8]
