from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import select

from app.db.models import TelegramAccessEntry, utcnow
from app.services.telegram_access_service import AccessEntry, TelegramAccessUnavailable


def _is_missing_access_table(exc: ProgrammingError) -> bool:
    rendered = str(exc)
    return "telegram_access_entries" in rendered and (
        "UndefinedTableError" in rendered or "does not exist" in rendered
    )


class TelegramAccessRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_entry(self, entry_type: str, telegram_id: int) -> AccessEntry | None:
        try:
            result = await self.session.execute(
                select(TelegramAccessEntry).where(
                    TelegramAccessEntry.entry_type == entry_type,
                    TelegramAccessEntry.telegram_id == telegram_id,
                )
            )
        except ProgrammingError as exc:
            await self.session.rollback()
            if _is_missing_access_table(exc):
                raise TelegramAccessUnavailable("telegram_access_entries_unavailable") from exc
            raise
        entry = result.scalar_one_or_none()
        if entry is None:
            return None
        return _to_access_entry(entry)

    async def list_entries(self, entry_type: str) -> list[AccessEntry]:
        try:
            result = await self.session.execute(
                select(TelegramAccessEntry)
                .where(TelegramAccessEntry.entry_type == entry_type)
                .order_by(TelegramAccessEntry.telegram_id)
            )
        except ProgrammingError as exc:
            await self.session.rollback()
            if _is_missing_access_table(exc):
                raise TelegramAccessUnavailable("telegram_access_entries_unavailable") from exc
            raise
        return [_to_access_entry(entry) for entry in result.scalars().all()]

    async def upsert_entry(
        self,
        *,
        entry_type: str,
        telegram_id: int,
        label: str | None,
        created_by: int | None,
    ) -> None:
        now = utcnow()
        statement = (
            insert(TelegramAccessEntry)
            .values(
                entry_type=entry_type,
                telegram_id=telegram_id,
                label=label,
                created_by=created_by,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_update(
                index_elements=[
                    TelegramAccessEntry.entry_type,
                    TelegramAccessEntry.telegram_id,
                ],
                set_={
                    "label": label,
                    "created_by": created_by,
                    "updated_at": now,
                },
            )
        )
        try:
            await self.session.execute(statement)
            await self.session.commit()
        except ProgrammingError as exc:
            await self.session.rollback()
            if _is_missing_access_table(exc):
                raise TelegramAccessUnavailable("telegram_access_entries_unavailable") from exc
            raise

    async def delete_entry(self, entry_type: str, telegram_id: int) -> bool:
        existing = await self.get_entry(entry_type, telegram_id)
        statement = delete(TelegramAccessEntry).where(
            TelegramAccessEntry.entry_type == entry_type,
            TelegramAccessEntry.telegram_id == telegram_id,
        )
        try:
            await self.session.execute(statement)
            await self.session.commit()
        except ProgrammingError as exc:
            await self.session.rollback()
            if _is_missing_access_table(exc):
                raise TelegramAccessUnavailable("telegram_access_entries_unavailable") from exc
            raise
        return existing is not None


def _to_access_entry(entry: TelegramAccessEntry) -> AccessEntry:
    return AccessEntry(
        entry_type=entry.entry_type,
        telegram_id=entry.telegram_id,
        label=entry.label,
        created_by=entry.created_by,
    )
