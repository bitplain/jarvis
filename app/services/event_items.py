from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol
from uuid import uuid4

from app.db.models import EventPriority, EventScope, EventStatus, EventType

DEFAULT_DIGEST_TIMEZONE = "Europe/Moscow"
INBOX_SCOPES = {EventScope.PERSONAL.value, EventScope.HOUSEHOLD.value}
WORK_SCOPES = {EventScope.WORK.value}
ACTIVE_EVENT_STATUSES = {
    EventStatus.NEW.value,
    EventStatus.SEEN.value,
    EventStatus.SNOOZED.value,
}
DIGEST_EVENT_STATUSES = {EventStatus.NEW.value, EventStatus.SNOOZED.value}
EVENT_PRIORITY_RANK = {
    EventPriority.LOW.value: 0,
    EventPriority.NORMAL.value: 1,
    EventPriority.HIGH.value: 2,
    EventPriority.CRITICAL.value: 3,
}
VALID_EVENT_SCOPES = {scope.value for scope in EventScope}
VALID_EVENT_STATUSES = {status.value for status in EventStatus}
VALID_EVENT_PRIORITIES = {priority.value for priority in EventPriority}
VALID_EVENT_TYPES = {event_type.value for event_type in EventType}


@dataclass(frozen=True)
class EventItemCreate:
    user_id: int | None
    chat_id: int | None
    scope: EventScope | str
    event_type: EventType | str
    title: str
    body: str
    source: str
    priority: EventPriority | str = EventPriority.NORMAL
    status: EventStatus | str = EventStatus.NEW
    payload_json: dict[str, Any] | None = None
    card_json: dict[str, Any] | None = None
    due_at: datetime | None = None


def create_personal_event(**kwargs: Any) -> EventItemCreate:
    return EventItemCreate(scope=EventScope.PERSONAL, **kwargs)


def create_household_event(**kwargs: Any) -> EventItemCreate:
    return EventItemCreate(scope=EventScope.HOUSEHOLD, **kwargs)


def create_work_event(**kwargs: Any) -> EventItemCreate:
    return EventItemCreate(scope=EventScope.WORK, **kwargs)


def create_system_event(**kwargs: Any) -> EventItemCreate:
    return EventItemCreate(scope=EventScope.SYSTEM, **kwargs)


@dataclass
class StoredEventItem:
    id: str
    user_id: int | None
    chat_id: int | None
    scope: str
    event_type: str
    title: str
    body: str
    priority: str
    status: str
    source: str
    payload_json: dict[str, Any]
    card_json: dict[str, Any] | None
    due_at: datetime | None
    created_at: datetime
    updated_at: datetime


class EventItemRepositoryProtocol(Protocol):
    async def create(self, event: EventItemCreate, *, now: datetime) -> StoredEventItem:
        raise NotImplementedError

    async def list_active(
        self,
        *,
        user_id: int,
        chat_id: int,
        scopes: set[str],
        limit: int,
    ) -> list[StoredEventItem]:
        raise NotImplementedError

    async def list_for_digest(
        self,
        *,
        scopes: set[str],
        now: datetime,
        limit: int,
    ) -> list[StoredEventItem]:
        raise NotImplementedError

    async def get(self, event_id: str) -> StoredEventItem | None:
        raise NotImplementedError

    async def set_status(
        self,
        event_id: str,
        *,
        status: str,
        now: datetime,
    ) -> StoredEventItem | None:
        raise NotImplementedError


class EventItemService:
    def __init__(
        self,
        repository: EventItemRepositoryProtocol,
        *,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.now_factory = now_factory or (lambda: datetime.now(UTC))

    @classmethod
    def in_memory(
        cls,
        *,
        now_factory: Callable[[], datetime] | None = None,
    ) -> EventItemService:
        return cls(InMemoryEventItemRepository(), now_factory=now_factory)

    async def create_event(self, event: EventItemCreate) -> StoredEventItem:
        normalized = EventItemCreate(
            user_id=event.user_id,
            chat_id=event.chat_id,
            scope=_normalize_value(event.scope, VALID_EVENT_SCOPES, "invalid_event_scope"),
            event_type=_normalize_value(
                event.event_type,
                VALID_EVENT_TYPES,
                "invalid_event_type",
            ),
            title=_required_text(event.title, "event_title_required"),
            body=" ".join(event.body.strip().split()),
            source=_required_text(event.source, "event_source_required"),
            priority=_normalize_value(
                event.priority,
                VALID_EVENT_PRIORITIES,
                "invalid_event_priority",
            ),
            status=_normalize_value(event.status, VALID_EVENT_STATUSES, "invalid_event_status"),
            payload_json=dict(event.payload_json or {}),
            card_json=_json_object_or_none(event.card_json),
            due_at=_to_utc_or_none(event.due_at),
        )
        return await self.repository.create(normalized, now=_to_utc(self.now_factory()))

    async def list_for_inbox(
        self,
        *,
        user_id: int,
        chat_id: int,
        limit: int = 10,
    ) -> list[StoredEventItem]:
        return await self.repository.list_active(
            user_id=user_id,
            chat_id=chat_id,
            scopes=set(INBOX_SCOPES),
            limit=limit,
        )

    async def list_for_work(
        self,
        *,
        user_id: int,
        chat_id: int,
        limit: int = 10,
    ) -> list[StoredEventItem]:
        return await self.repository.list_active(
            user_id=user_id,
            chat_id=chat_id,
            scopes=set(WORK_SCOPES),
            limit=limit,
        )

    async def list_for_digest(
        self,
        *,
        scopes: set[str],
        now: datetime,
        limit: int = 15,
    ) -> list[StoredEventItem]:
        normalized_scopes = {
            _normalize_value(scope, VALID_EVENT_SCOPES, "invalid_event_scope")
            for scope in scopes
        }
        return await self.repository.list_for_digest(
            scopes=normalized_scopes,
            now=_to_utc(now),
            limit=limit,
        )

    async def get_event(self, event_id: str) -> StoredEventItem | None:
        return await self.repository.get(event_id)

    async def mark_done(self, event_id: str) -> StoredEventItem | None:
        return await self.repository.set_status(
            event_id,
            status=EventStatus.DONE.value,
            now=_to_utc(self.now_factory()),
        )

    async def snooze_event(self, event_id: str) -> StoredEventItem | None:
        return await self.repository.set_status(
            event_id,
            status=EventStatus.SNOOZED.value,
            now=_to_utc(self.now_factory()),
        )


class InMemoryEventItemRepository:
    def __init__(self) -> None:
        self.items: dict[str, StoredEventItem] = {}

    async def create(self, event: EventItemCreate, *, now: datetime) -> StoredEventItem:
        stored = StoredEventItem(
            id=uuid4().hex,
            user_id=event.user_id,
            chat_id=event.chat_id,
            scope=str(event.scope),
            event_type=str(event.event_type),
            title=event.title,
            body=event.body,
            priority=str(event.priority),
            status=str(event.status),
            source=event.source,
            payload_json=dict(event.payload_json or {}),
            card_json=_json_object_or_none(event.card_json),
            due_at=event.due_at,
            created_at=now,
            updated_at=now,
        )
        self.items[stored.id] = stored
        return stored

    async def list_active(
        self,
        *,
        user_id: int,
        chat_id: int,
        scopes: set[str],
        limit: int,
    ) -> list[StoredEventItem]:
        events = [
            event
            for event in self.items.values()
            if event.scope in scopes
            and event.status in ACTIVE_EVENT_STATUSES
            and (event.user_id == user_id or event.chat_id == chat_id)
        ]
        return sorted(events, key=_event_sort_key)[:limit]

    async def list_for_digest(
        self,
        *,
        scopes: set[str],
        now: datetime,
        limit: int,
    ) -> list[StoredEventItem]:
        events = [
            event
            for event in self.items.values()
            if event.scope in scopes
            and (
                event.status == EventStatus.NEW.value
                or (
                    event.status == EventStatus.SNOOZED.value
                    and event.due_at is not None
                    and event.due_at <= now
                )
            )
        ]
        return sorted(events, key=_event_sort_key)[:limit]

    async def get(self, event_id: str) -> StoredEventItem | None:
        return self.items.get(event_id.strip().lower().replace("-", ""))

    async def set_status(
        self,
        event_id: str,
        *,
        status: str,
        now: datetime,
    ) -> StoredEventItem | None:
        event = await self.get(event_id)
        if event is None:
            return None
        event.status = status
        event.updated_at = now
        return event


def _event_sort_key(event: StoredEventItem) -> tuple[int, bool, datetime, float]:
    due_at = event.due_at or datetime.max.replace(tzinfo=UTC)
    return (
        -EVENT_PRIORITY_RANK.get(event.priority, EVENT_PRIORITY_RANK[EventPriority.NORMAL.value]),
        event.due_at is None,
        due_at,
        -event.created_at.timestamp(),
    )


def _normalize_value(value: StrEnum | str, allowed: set[str], error_code: str) -> str:
    normalized = value.value if isinstance(value, StrEnum) else str(value)
    normalized = normalized.strip().lower()
    if normalized not in allowed:
        raise ValueError(error_code)
    return normalized


def _required_text(value: str, error_code: str) -> str:
    normalized = " ".join(value.strip().split())
    if not normalized:
        raise ValueError(error_code)
    return normalized


def _json_object_or_none(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    return dict(value)


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _to_utc_or_none(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return _to_utc(value)
