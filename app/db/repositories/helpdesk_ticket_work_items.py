from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import cast, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.sqltypes import String

from app.db.models import HelpdeskTicketWorkItem, utcnow
from app.services.helpdesk_ticket_workflow import (
    ACTIVE_STATUSES,
    DISMISSED,
    DONE,
    IN_WORK,
    IN_WORK_INTERVAL_MINUTES,
    WAITING_ACK,
    WAITING_ACK_INTERVAL_MINUTES,
    StoredHelpdeskTicketWorkItem,
)


class HelpdeskTicketWorkItemRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert_waiting_ack(
        self,
        *,
        glpi_ticket_id: str,
        latest_event_id: str | None,
        title: str,
        telegram_chat_id: int,
        now: datetime,
    ) -> StoredHelpdeskTicketWorkItem:
        item = await self._get_by_ticket_chat(glpi_ticket_id, telegram_chat_id)
        parsed_event_id = _uuid_or_none(latest_event_id)
        if item is None:
            item = HelpdeskTicketWorkItem(
                glpi_ticket_id=glpi_ticket_id,
                latest_event_id=parsed_event_id,
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
            self.session.add(item)
            await self.session.commit()
            await self.session.refresh(item)
            return _to_stored(item)
        item.latest_event_id = parsed_event_id
        item.title = title
        item.updated_at = now
        if item.status == WAITING_ACK:
            item.reminder_interval_minutes = WAITING_ACK_INTERVAL_MINUTES
            if item.next_reminder_at is None:
                item.next_reminder_at = now + timedelta(minutes=WAITING_ACK_INTERVAL_MINUTES)
        await self.session.commit()
        await self.session.refresh(item)
        return _to_stored(item)

    async def get(self, item_id: str) -> StoredHelpdeskTicketWorkItem | None:
        item = await self._get_model(item_id)
        return _to_stored(item) if item is not None else None

    async def list_in_work(self, *, telegram_chat_id: int) -> list[StoredHelpdeskTicketWorkItem]:
        result = await self.session.execute(
            select(HelpdeskTicketWorkItem)
            .where(
                HelpdeskTicketWorkItem.telegram_chat_id == telegram_chat_id,
                HelpdeskTicketWorkItem.status == IN_WORK,
            )
            .order_by(HelpdeskTicketWorkItem.assigned_at, HelpdeskTicketWorkItem.updated_at)
        )
        return [_to_stored(item) for item in result.scalars().all()]

    async def take(
        self,
        item_id: str,
        *,
        actor_user_id: int,
        telegram_chat_id: int,
        now: datetime,
    ) -> StoredHelpdeskTicketWorkItem | None:
        item = await self._get_model(item_id)
        if item is None or item.telegram_chat_id != telegram_chat_id:
            return None
        if item.status in {DONE, DISMISSED}:
            return _to_stored(item)
        item.status = IN_WORK
        item.assigned_by_user_id = actor_user_id
        item.assigned_at = item.assigned_at or now
        item.reminder_interval_minutes = IN_WORK_INTERVAL_MINUTES
        item.next_reminder_at = now + timedelta(minutes=IN_WORK_INTERVAL_MINUTES)
        item.updated_at = now
        await self.session.commit()
        await self.session.refresh(item)
        return _to_stored(item)

    async def mark_done(
        self,
        item_id: str,
        *,
        actor_user_id: int,
        telegram_chat_id: int,
        now: datetime,
    ) -> StoredHelpdeskTicketWorkItem | None:
        del actor_user_id
        item = await self._get_model(item_id)
        if item is None or item.telegram_chat_id != telegram_chat_id:
            return None
        item.status = DONE
        item.done_at = item.done_at or now
        item.next_reminder_at = None
        item.updated_at = now
        await self.session.commit()
        await self.session.refresh(item)
        return _to_stored(item)

    async def snooze(
        self,
        item_id: str,
        *,
        minutes: int,
        telegram_chat_id: int,
        now: datetime,
    ) -> StoredHelpdeskTicketWorkItem | None:
        item = await self._get_model(item_id)
        if item is None or item.telegram_chat_id != telegram_chat_id:
            return None
        if item.status not in ACTIVE_STATUSES:
            return _to_stored(item)
        item.next_reminder_at = now + timedelta(minutes=minutes)
        item.updated_at = now
        await self.session.commit()
        await self.session.refresh(item)
        return _to_stored(item)

    async def due_reminders(
        self,
        now: datetime,
        *,
        limit: int,
    ) -> list[StoredHelpdeskTicketWorkItem]:
        result = await self.session.execute(
            select(HelpdeskTicketWorkItem)
            .where(
                HelpdeskTicketWorkItem.status.in_(ACTIVE_STATUSES),
                HelpdeskTicketWorkItem.next_reminder_at.is_not(None),
                HelpdeskTicketWorkItem.next_reminder_at <= now,
            )
            .order_by(HelpdeskTicketWorkItem.next_reminder_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return [_to_stored(item) for item in result.scalars().all()]

    async def mark_reminded(
        self,
        item_id: str,
        *,
        now: datetime,
    ) -> StoredHelpdeskTicketWorkItem | None:
        item = await self._get_model(item_id)
        if item is None or item.status not in ACTIVE_STATUSES:
            return None
        item.last_reminded_at = now
        item.next_reminder_at = now + timedelta(minutes=item.reminder_interval_minutes)
        item.updated_at = utcnow()
        await self.session.commit()
        await self.session.refresh(item)
        return _to_stored(item)

    async def _get_by_ticket_chat(
        self,
        glpi_ticket_id: str,
        telegram_chat_id: int,
    ) -> HelpdeskTicketWorkItem | None:
        result = await self.session.execute(
            select(HelpdeskTicketWorkItem).where(
                HelpdeskTicketWorkItem.glpi_ticket_id == glpi_ticket_id,
                HelpdeskTicketWorkItem.telegram_chat_id == telegram_chat_id,
            )
        )
        return result.scalar_one_or_none()

    async def _get_model(self, item_id: str) -> HelpdeskTicketWorkItem | None:
        parsed = _uuid_or_none(item_id)
        if parsed is not None:
            result = await self.session.execute(
                select(HelpdeskTicketWorkItem).where(HelpdeskTicketWorkItem.id == parsed)
            )
            return result.scalar_one_or_none()
        compact = item_id.replace("-", "")
        result = await self.session.execute(
            select(HelpdeskTicketWorkItem)
            .where(cast(HelpdeskTicketWorkItem.id, String).like(f"{compact}%"))
            .order_by(HelpdeskTicketWorkItem.created_at)
            .limit(1)
        )
        return result.scalar_one_or_none()


def _uuid_or_none(value: str | None) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def _to_stored(item: HelpdeskTicketWorkItem) -> StoredHelpdeskTicketWorkItem:
    return StoredHelpdeskTicketWorkItem(
        id=str(item.id),
        glpi_ticket_id=item.glpi_ticket_id,
        latest_event_id=str(item.latest_event_id) if item.latest_event_id is not None else None,
        title=item.title,
        status=item.status,
        telegram_chat_id=item.telegram_chat_id,
        assigned_by_user_id=item.assigned_by_user_id,
        assigned_at=item.assigned_at,
        done_at=item.done_at,
        next_reminder_at=item.next_reminder_at,
        last_reminded_at=item.last_reminded_at,
        reminder_interval_minutes=item.reminder_interval_minutes,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )
