from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, case, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import select

from app.db.models import EventItem
from app.services.event_items import (
    ACTIVE_EVENT_STATUSES,
    EVENT_PRIORITY_RANK,
    EventItemCreate,
    StoredEventItem,
)


class EventItemRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, event: EventItemCreate, *, now: datetime) -> StoredEventItem:
        item = EventItem(
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
            card_json=dict(event.card_json) if event.card_json is not None else None,
            due_at=event.due_at,
            created_at=now,
            updated_at=now,
        )
        self.session.add(item)
        await self.session.commit()
        await self.session.refresh(item)
        return _to_stored(item)

    async def list_active(
        self,
        *,
        user_id: int,
        chat_id: int,
        scopes: set[str],
        limit: int,
    ) -> list[StoredEventItem]:
        priority_rank = case(
            *[
                (EventItem.priority == priority, rank)
                for priority, rank in EVENT_PRIORITY_RANK.items()
            ],
            else_=EVENT_PRIORITY_RANK["normal"],
        )
        due_is_null = case((EventItem.due_at.is_(None), 1), else_=0)
        statement = (
            select(EventItem)
            .where(
                EventItem.scope.in_(scopes),
                EventItem.status.in_(ACTIVE_EVENT_STATUSES),
                or_(EventItem.user_id == user_id, EventItem.chat_id == chat_id),
            )
            .order_by(
                priority_rank.desc(),
                due_is_null,
                EventItem.due_at,
                EventItem.created_at.desc(),
            )
            .limit(limit)
        )
        result = await self.session.execute(statement)
        return [_to_stored(item) for item in result.scalars().all()]

    async def list_for_digest(
        self,
        *,
        scopes: set[str],
        now: datetime,
        limit: int,
    ) -> list[StoredEventItem]:
        priority_rank = case(
            *[
                (EventItem.priority == priority, rank)
                for priority, rank in EVENT_PRIORITY_RANK.items()
            ],
            else_=EVENT_PRIORITY_RANK["normal"],
        )
        due_is_null = case((EventItem.due_at.is_(None), 1), else_=0)
        statement = (
            select(EventItem)
            .where(
                EventItem.scope.in_(scopes),
                or_(
                    EventItem.status == "new",
                    and_(EventItem.status == "snoozed", EventItem.due_at <= now),
                ),
            )
            .order_by(
                priority_rank.desc(),
                due_is_null,
                EventItem.due_at,
                EventItem.created_at.desc(),
            )
            .limit(limit)
        )
        result = await self.session.execute(statement)
        return [_to_stored(item) for item in result.scalars().all()]

    async def get(self, event_id: str) -> StoredEventItem | None:
        item = await self._get_model(event_id)
        return _to_stored(item) if item is not None else None

    async def get_by_payload_identity(
        self,
        *,
        source: str,
        event_type: str,
        user_id: int | None,
        identity_key: str,
    ) -> StoredEventItem | None:
        identity_expr = EventItem.payload_json.op("->>")("identity_key")
        statement = (
            select(EventItem)
            .where(
                EventItem.source == source,
                EventItem.event_type == event_type,
                EventItem.user_id == user_id,
                identity_expr == identity_key,
            )
            .order_by(EventItem.updated_at.desc())
            .limit(1)
        )
        result = await self.session.execute(statement)
        item = result.scalar_one_or_none()
        return _to_stored(item) if item is not None else None

    async def update_from_event(
        self,
        event_id: str,
        event: EventItemCreate,
        *,
        now: datetime,
        status: str | None = None,
    ) -> StoredEventItem | None:
        item = await self._get_model(event_id)
        if item is None:
            return None
        item.user_id = event.user_id
        item.chat_id = event.chat_id
        item.scope = str(event.scope)
        item.event_type = str(event.event_type)
        item.title = event.title
        item.body = event.body
        item.priority = str(event.priority)
        item.status = status if status is not None else str(event.status)
        item.source = event.source
        item.payload_json = dict(event.payload_json or {})
        item.card_json = dict(event.card_json) if event.card_json is not None else None
        item.due_at = event.due_at
        item.updated_at = now
        await self.session.commit()
        await self.session.refresh(item)
        return _to_stored(item)

    async def set_status(
        self,
        event_id: str,
        *,
        status: str,
        now: datetime,
    ) -> StoredEventItem | None:
        item = await self._get_model(event_id)
        if item is None:
            return None
        item.status = status
        item.updated_at = now
        await self.session.commit()
        await self.session.refresh(item)
        return _to_stored(item)

    async def _get_model(self, event_id: str) -> EventItem | None:
        event_uuid = _uuid_or_none(event_id)
        if event_uuid is None:
            return None
        result = await self.session.execute(select(EventItem).where(EventItem.id == event_uuid))
        return result.scalar_one_or_none()


def _uuid_or_none(value: str) -> UUID | None:
    try:
        return UUID(value.strip())
    except ValueError:
        return None


def _to_stored(item: EventItem) -> StoredEventItem:
    return StoredEventItem(
        id=item.id.hex,
        user_id=item.user_id,
        chat_id=item.chat_id,
        scope=item.scope,
        event_type=item.event_type,
        title=item.title,
        body=item.body,
        priority=item.priority,
        status=item.status,
        source=item.source,
        payload_json=dict(item.payload_json or {}),
        card_json=_json_object_or_none(item.card_json),
        due_at=item.due_at,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _json_object_or_none(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    return dict(value)
