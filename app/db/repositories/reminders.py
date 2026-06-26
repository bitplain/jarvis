from datetime import datetime
from uuid import UUID

from sqlalchemy import cast, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import select
from sqlalchemy.sql.sqltypes import String

from app.db.models import Reminder, utcnow
from app.services.reminder_service import StoredReminder


class ReminderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        scope_type: str,
        chat_id: int,
        user_id: int,
        text: str,
        remind_at: datetime,
    ) -> StoredReminder:
        now = utcnow()
        reminder = Reminder(
            scope_type=scope_type,
            chat_id=chat_id,
            user_id=user_id,
            text=text,
            remind_at=remind_at,
            status="scheduled",
            created_at=now,
            updated_at=now,
        )
        self.session.add(reminder)
        await self.session.commit()
        await self.session.refresh(reminder)
        return _to_stored(reminder)

    async def list_scheduled(
        self,
        *,
        scope_type: str,
        chat_id: int,
        user_id: int | None,
    ) -> list[StoredReminder]:
        statement = (
            select(Reminder)
            .where(
                Reminder.scope_type == scope_type,
                Reminder.chat_id == chat_id,
                Reminder.status == "scheduled",
            )
            .order_by(Reminder.remind_at)
        )
        if user_id is not None and scope_type == "private":
            statement = statement.where(Reminder.user_id == user_id)
        result = await self.session.execute(statement)
        return [_to_stored(reminder) for reminder in result.scalars().all()]

    async def get(self, reminder_id: str) -> StoredReminder | None:
        reminder = await self._get_model(reminder_id)
        return _to_stored(reminder) if reminder is not None else None

    async def set_status(
        self,
        reminder_id: str,
        *,
        status: str,
        remind_at: datetime | None = None,
    ) -> StoredReminder | None:
        reminder = await self._get_model(reminder_id)
        if reminder is None:
            return None
        reminder.status = status
        reminder.updated_at = utcnow()
        if remind_at is not None:
            reminder.remind_at = remind_at
        if status == "sent":
            reminder.sent_at = utcnow()
        await self.session.commit()
        await self.session.refresh(reminder)
        return _to_stored(reminder)

    async def due(self, now: datetime, *, limit: int) -> list[StoredReminder]:
        statement = (
            select(Reminder)
            .where(Reminder.status == "scheduled", Reminder.remind_at <= now)
            .order_by(Reminder.remind_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        result = await self.session.execute(statement)
        return [_to_stored(reminder) for reminder in result.scalars().all()]

    async def claim_due(self, now: datetime, *, limit: int) -> list[StoredReminder]:
        reminders = await self.due(now, limit=limit)
        if not reminders:
            return []
        ids = [_uuid(reminder.id) for reminder in reminders]
        await self.session.execute(
            update(Reminder)
            .where(Reminder.id.in_(ids), Reminder.status == "scheduled")
            .values(status="sent", sent_at=utcnow(), updated_at=utcnow())
        )
        await self.session.commit()
        return reminders

    async def _get_model(self, reminder_id: str) -> Reminder | None:
        parsed = _uuid_or_none(reminder_id)
        if parsed is not None:
            result = await self.session.execute(select(Reminder).where(Reminder.id == parsed))
        else:
            result = await self.session.execute(
                select(Reminder)
                .where(cast(Reminder.id, String).like(f"{reminder_id}%"))
                .order_by(Reminder.created_at)
                .limit(1)
            )
        return result.scalar_one_or_none()


def _uuid(value: str) -> UUID:
    return UUID(value)


def _uuid_or_none(value: str) -> UUID | None:
    try:
        return UUID(value)
    except ValueError:
        return None


def _to_stored(reminder: Reminder) -> StoredReminder:
    return StoredReminder(
        id=reminder.id.hex,
        scope_type=reminder.scope_type,
        chat_id=reminder.chat_id,
        user_id=reminder.user_id,
        text=reminder.text,
        remind_at=reminder.remind_at,
        status=reminder.status,
        sent_at=reminder.sent_at,
    )
