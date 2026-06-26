from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import uuid4

REMINDER_SCOPE_TYPES = {"private", "group"}


@dataclass(frozen=True)
class ReminderView:
    id: str
    scope_type: str
    chat_id: int
    user_id: int
    text: str
    remind_at: datetime
    status: str


@dataclass
class StoredReminder:
    id: str
    scope_type: str
    chat_id: int
    user_id: int
    text: str
    remind_at: datetime
    status: str
    sent_at: datetime | None = None


class ReminderRepositoryProtocol(Protocol):
    async def create(
        self,
        *,
        scope_type: str,
        chat_id: int,
        user_id: int,
        text: str,
        remind_at: datetime,
    ) -> StoredReminder:
        raise NotImplementedError

    async def list_scheduled(
        self,
        *,
        scope_type: str,
        chat_id: int,
        user_id: int | None,
    ) -> list[StoredReminder]:
        raise NotImplementedError

    async def get(self, reminder_id: str) -> StoredReminder | None:
        raise NotImplementedError

    async def set_status(
        self,
        reminder_id: str,
        *,
        status: str,
        remind_at: datetime | None = None,
    ) -> StoredReminder | None:
        raise NotImplementedError

    async def due(self, now: datetime, *, limit: int) -> list[StoredReminder]:
        raise NotImplementedError


class ReminderService:
    def __init__(
        self,
        repository: ReminderRepositoryProtocol,
        *,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.now_factory = now_factory or (lambda: datetime.now(UTC))

    @classmethod
    def in_memory(cls, *, now_factory: Callable[[], datetime] | None = None) -> ReminderService:
        return cls(InMemoryReminderRepository(), now_factory=now_factory)

    async def create_reminder(
        self,
        scope: str,
        chat_id: int,
        user_id: int,
        text: str,
        remind_at: datetime,
    ) -> ReminderView:
        reminder = await self.repository.create(
            scope_type=_normalize_scope(scope),
            chat_id=chat_id,
            user_id=user_id,
            text=" ".join(text.strip().split()),
            remind_at=_to_utc(remind_at),
        )
        return _to_view(reminder)

    async def list_reminders(
        self,
        scope: str,
        chat_id: int,
        user_id: int | None,
    ) -> list[ReminderView]:
        reminders = await self.repository.list_scheduled(
            scope_type=_normalize_scope(scope),
            chat_id=chat_id,
            user_id=user_id,
        )
        return [_to_view(reminder) for reminder in reminders]

    async def cancel_reminder(
        self,
        reminder_id: str,
        actor_user_id: int,
    ) -> list[ReminderView]:
        del actor_user_id
        reminder = await self.repository.get(reminder_id)
        if reminder is None:
            return []
        await self.repository.set_status(reminder_id, status="cancelled")
        return await self.list_reminders(reminder.scope_type, reminder.chat_id, None)

    async def snooze_reminder(
        self,
        reminder_id: str,
        delta: timedelta,
        actor_user_id: int,
    ) -> ReminderView:
        del actor_user_id
        reminder = await self.repository.get(reminder_id)
        if reminder is None:
            raise ValueError("reminder_not_found")
        now = _to_utc(self.now_factory())
        remind_at = max(now, reminder.remind_at) + delta
        updated = await self.repository.set_status(
            reminder_id,
            status="scheduled",
            remind_at=remind_at,
        )
        if updated is None:
            raise ValueError("reminder_not_found")
        return _to_view(updated)

    async def mark_sent(self, reminder_id: str) -> None:
        await self.repository.set_status(reminder_id, status="sent")

    async def due_reminders(self, now: datetime) -> list[ReminderView]:
        reminders = await self.repository.due(_to_utc(now), limit=50)
        return [_to_view(reminder) for reminder in reminders]


class InMemoryReminderRepository:
    def __init__(self) -> None:
        self.reminders: dict[str, StoredReminder] = {}

    async def create(
        self,
        *,
        scope_type: str,
        chat_id: int,
        user_id: int,
        text: str,
        remind_at: datetime,
    ) -> StoredReminder:
        reminder = StoredReminder(
            id=uuid4().hex,
            scope_type=scope_type,
            chat_id=chat_id,
            user_id=user_id,
            text=text[:500],
            remind_at=remind_at,
            status="scheduled",
        )
        self.reminders[reminder.id] = reminder
        return reminder

    async def list_scheduled(
        self,
        *,
        scope_type: str,
        chat_id: int,
        user_id: int | None,
    ) -> list[StoredReminder]:
        return sorted(
            [
                reminder
                for reminder in self.reminders.values()
                if reminder.scope_type == scope_type
                and reminder.chat_id == chat_id
                and reminder.status == "scheduled"
                and (user_id is None or reminder.user_id == user_id)
            ],
            key=lambda reminder: reminder.remind_at,
        )

    async def get(self, reminder_id: str) -> StoredReminder | None:
        return self.reminders.get(reminder_id)

    async def set_status(
        self,
        reminder_id: str,
        *,
        status: str,
        remind_at: datetime | None = None,
    ) -> StoredReminder | None:
        reminder = self.reminders.get(reminder_id)
        if reminder is None:
            return None
        reminder.status = status
        if remind_at is not None:
            reminder.remind_at = remind_at
        if status == "sent":
            reminder.sent_at = datetime.now(UTC)
        return reminder

    async def due(self, now: datetime, *, limit: int) -> list[StoredReminder]:
        return sorted(
            [
                reminder
                for reminder in self.reminders.values()
                if reminder.status == "scheduled" and reminder.remind_at <= now
            ],
            key=lambda reminder: reminder.remind_at,
        )[:limit]


def _normalize_scope(scope: str) -> str:
    if scope not in REMINDER_SCOPE_TYPES:
        raise ValueError("invalid_reminder_scope")
    return scope


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _to_view(reminder: StoredReminder) -> ReminderView:
    return ReminderView(
        id=reminder.id,
        scope_type=reminder.scope_type,
        chat_id=reminder.chat_id,
        user_id=reminder.user_id,
        text=reminder.text,
        remind_at=reminder.remind_at,
        status=reminder.status,
    )
