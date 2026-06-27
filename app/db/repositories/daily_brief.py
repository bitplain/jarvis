from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import select

from app.db.models import DailyBriefSettings, utcnow
from app.services.daily_brief_service import (
    DailyBriefSettingsInput,
    StoredDailyBriefSettings,
    _timezone,
    _validate_scope,
    _validate_send_time,
)


class DailyBriefSettingsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_or_create(
        self,
        *,
        scope_type: str,
        chat_id: int,
        user_id: int | None,
    ) -> StoredDailyBriefSettings:
        existing = await self._find(scope_type=scope_type, chat_id=chat_id, user_id=user_id)
        if existing is not None:
            return _to_stored(existing)
        now = utcnow()
        settings = DailyBriefSettings(
            scope_type=scope_type,
            chat_id=chat_id,
            user_id=user_id,
            enabled=False,
            send_time="09:00",
            timezone="Europe/Moscow",
            created_at=now,
            updated_at=now,
        )
        self.session.add(settings)
        await self.session.commit()
        await self.session.refresh(settings)
        return _to_stored(settings)

    async def upsert(self, value: DailyBriefSettingsInput) -> StoredDailyBriefSettings:
        _validate_scope(value.scope_type)
        _validate_send_time(value.send_time)
        _timezone(value.timezone)
        existing = await self._find(
            scope_type=value.scope_type,
            chat_id=value.chat_id,
            user_id=value.user_id,
        )
        if existing is None:
            now = utcnow()
            settings = DailyBriefSettings(
                scope_type=value.scope_type,
                chat_id=value.chat_id,
                user_id=value.user_id,
                enabled=value.enabled,
                send_time=value.send_time,
                timezone=value.timezone,
                created_at=now,
                updated_at=now,
            )
            self.session.add(settings)
            await self.session.commit()
            await self.session.refresh(settings)
            return _to_stored(settings)
        existing.enabled = value.enabled
        existing.send_time = value.send_time
        existing.timezone = value.timezone
        existing.updated_at = utcnow()
        await self.session.commit()
        await self.session.refresh(existing)
        return _to_stored(existing)

    async def due_for_delivery(self, now: datetime) -> list[StoredDailyBriefSettings]:
        result = await self.session.execute(
            select(DailyBriefSettings)
            .where(DailyBriefSettings.enabled.is_(True))
            .order_by(DailyBriefSettings.updated_at)
        )
        due = []
        for settings in result.scalars().all():
            timezone = _timezone(settings.timezone)
            local_now = now.astimezone(timezone)
            if (
                local_now.strftime("%H:%M") == settings.send_time
                and settings.last_sent_date != local_now.date()
            ):
                due.append(_to_stored(settings))
        return due

    async def mark_sent_if_due(self, settings_id: str, local_date: str | date) -> bool:
        parsed_date = date.fromisoformat(local_date) if isinstance(local_date, str) else local_date
        result = await self.session.execute(
            update(DailyBriefSettings)
            .where(
                DailyBriefSettings.id == _uuid(settings_id),
                DailyBriefSettings.last_sent_date.is_distinct_from(parsed_date),
            )
            .values(last_sent_date=parsed_date, updated_at=utcnow())
        )
        await self.session.commit()
        return bool(getattr(result, "rowcount", 0))

    async def _find(
        self,
        *,
        scope_type: str,
        chat_id: int,
        user_id: int | None,
    ) -> DailyBriefSettings | None:
        statement = select(DailyBriefSettings).where(
            DailyBriefSettings.scope_type == scope_type,
            DailyBriefSettings.chat_id == chat_id,
        )
        if user_id is None:
            statement = statement.where(DailyBriefSettings.user_id.is_(None))
        else:
            statement = statement.where(DailyBriefSettings.user_id == user_id)
        result = await self.session.execute(statement.limit(1))
        return result.scalar_one_or_none()


def _uuid(value: str) -> UUID:
    return UUID(value)


def _to_stored(settings: DailyBriefSettings) -> StoredDailyBriefSettings:
    return StoredDailyBriefSettings(
        id=settings.id.hex,
        scope_type=settings.scope_type,
        chat_id=settings.chat_id,
        user_id=settings.user_id,
        enabled=settings.enabled,
        send_time=settings.send_time,
        timezone=settings.timezone,
        last_sent_date=settings.last_sent_date,
    )
