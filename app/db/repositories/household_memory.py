from __future__ import annotations

from uuid import UUID

from sqlalchemy import String, cast, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import select

from app.db.models import HouseholdMemoryEntry, utcnow


class HouseholdMemoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def active_count(self, *, scope_type: str, scope_chat_id: int) -> int:
        result = await self.session.execute(
            select(func.count(HouseholdMemoryEntry.id)).where(
                HouseholdMemoryEntry.scope_type == scope_type,
                HouseholdMemoryEntry.scope_chat_id == scope_chat_id,
                HouseholdMemoryEntry.status == "active",
            )
        )
        return int(result.scalar_one())

    async def create(
        self,
        *,
        scope_type: str,
        scope_chat_id: int,
        created_by_user_id: int,
        text: str,
    ) -> HouseholdMemoryEntry:
        now = utcnow()
        entry = HouseholdMemoryEntry(
            scope_type=scope_type,
            scope_chat_id=scope_chat_id,
            created_by_user_id=created_by_user_id,
            text=text,
            status="active",
            created_at=now,
            updated_at=now,
        )
        self.session.add(entry)
        await self.session.commit()
        await self.session.refresh(entry)
        return entry

    async def list_active(
        self,
        *,
        scope_type: str,
        scope_chat_id: int,
        limit: int = 100,
    ) -> list[HouseholdMemoryEntry]:
        result = await self.session.execute(
            select(HouseholdMemoryEntry)
            .where(
                HouseholdMemoryEntry.scope_type == scope_type,
                HouseholdMemoryEntry.scope_chat_id == scope_chat_id,
                HouseholdMemoryEntry.status == "active",
            )
            .order_by(HouseholdMemoryEntry.created_at)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def soft_delete(
        self,
        *,
        memory_id: str,
        actor_user_id: int,
    ) -> HouseholdMemoryEntry | None:
        entry = await self._get_active(memory_id)
        if entry is None:
            return None
        del actor_user_id
        entry.status = "deleted"
        entry.deleted_at = utcnow()
        entry.updated_at = utcnow()
        await self.session.commit()
        await self.session.refresh(entry)
        return entry

    async def soft_delete_many(self, memory_ids: list[str], *, actor_user_id: int) -> int:
        del actor_user_id
        parsed_ids = [_uuid(value) for value in memory_ids]
        parsed_ids = [value for value in parsed_ids if value is not None]
        if not parsed_ids:
            return 0
        result = await self.session.execute(
            update(HouseholdMemoryEntry)
            .where(
                HouseholdMemoryEntry.id.in_(parsed_ids),
                HouseholdMemoryEntry.status == "active",
            )
            .values(status="deleted", deleted_at=utcnow(), updated_at=utcnow())
        )
        await self.session.commit()
        return int(getattr(result, "rowcount", 0) or 0)

    async def _get_active(self, memory_id: str) -> HouseholdMemoryEntry | None:
        parsed = _uuid(memory_id)
        if parsed is not None:
            result = await self.session.execute(
                select(HouseholdMemoryEntry).where(
                    HouseholdMemoryEntry.id == parsed,
                    HouseholdMemoryEntry.status == "active",
                )
            )
            return result.scalar_one_or_none()
        result = await self.session.execute(
            select(HouseholdMemoryEntry)
            .where(
                cast(HouseholdMemoryEntry.id, String).like(f"{memory_id}%"),
                HouseholdMemoryEntry.status == "active",
            )
            .order_by(HouseholdMemoryEntry.created_at)
            .limit(1)
        )
        return result.scalar_one_or_none()


def _uuid(value: str) -> UUID | None:
    try:
        return UUID(value)
    except ValueError:
        return None
