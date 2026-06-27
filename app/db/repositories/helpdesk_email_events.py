from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import HelpdeskEmailEvent, utcnow


class HelpdeskEmailEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def exists(
        self,
        *,
        folder: str,
        imap_uid: str | None,
        message_id: str | None,
    ) -> bool:
        conditions = []
        if message_id:
            conditions.append(HelpdeskEmailEvent.message_id == message_id)
        if imap_uid:
            conditions.append(
                (HelpdeskEmailEvent.folder == folder) & (HelpdeskEmailEvent.imap_uid == imap_uid)
            )
        if not conditions:
            return False
        result = await self.session.execute(
            select(HelpdeskEmailEvent.id).where(or_(*conditions)).limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def create_event(self, **values: object) -> str | None:
        event = HelpdeskEmailEvent(**values)
        self.session.add(event)
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            return None
        await self.session.refresh(event)
        return str(event.id)

    async def mark_notified(
        self,
        event_id: str,
        *,
        telegram_chat_id: int,
        telegram_message_id: int,
    ) -> None:
        await self.session.execute(
            update(HelpdeskEmailEvent)
            .where(HelpdeskEmailEvent.id == _uuid(event_id))
            .values(
                notify_status="sent",
                telegram_chat_id=telegram_chat_id,
                telegram_message_id=telegram_message_id,
                error_code=None,
                updated_at=utcnow(),
            )
        )
        await self.session.commit()

    async def mark_notify_failed(self, event_id: str, *, error_code: str) -> None:
        await self.session.execute(
            update(HelpdeskEmailEvent)
            .where(HelpdeskEmailEvent.id == _uuid(event_id))
            .values(
                notify_status="failed",
                error_code=error_code,
                updated_at=utcnow(),
            )
        )
        await self.session.commit()

    async def processed_last_24h(self, *, now: datetime | None = None) -> int:
        threshold = (now or datetime.now(UTC)) - timedelta(hours=24)
        result = await self.session.execute(
            select(func.count(HelpdeskEmailEvent.id)).where(
                HelpdeskEmailEvent.created_at >= threshold
            )
        )
        return int(result.scalar_one())

    async def pending_notifications_count(self) -> int:
        result = await self.session.execute(
            select(func.count(HelpdeskEmailEvent.id)).where(
                HelpdeskEmailEvent.notify_status == "pending"
            )
        )
        return int(result.scalar_one())


def _uuid(value: str) -> UUID:
    return UUID(value)
