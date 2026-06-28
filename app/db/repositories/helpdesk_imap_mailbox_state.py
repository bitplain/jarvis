from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import HelpdeskImapMailboxState, utcnow


class HelpdeskImapMailboxStateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_state(self, *, folder: str) -> HelpdeskImapMailboxState | None:
        result = await self.session.execute(
            select(HelpdeskImapMailboxState).where(HelpdeskImapMailboxState.folder == folder)
        )
        return result.scalar_one_or_none()

    async def upsert_state(
        self,
        *,
        folder: str,
        uidvalidity: str | None,
        last_seen_uid: int | None,
        baseline: bool = False,
        last_error_code: str | None = None,
    ) -> HelpdeskImapMailboxState:
        now = utcnow()
        insert_values = {
            "folder": folder,
            "uidvalidity": uidvalidity,
            "last_seen_uid": last_seen_uid,
            "baseline_at": now if baseline else None,
            "last_check_at": now,
            "last_success_at": now if last_error_code is None else None,
            "last_error_code": last_error_code,
            "created_at": now,
            "updated_at": now,
        }
        update_values: dict[str, datetime | int | str | None] = {
            "uidvalidity": uidvalidity,
            "last_seen_uid": last_seen_uid,
            "last_check_at": now,
            "last_error_code": last_error_code,
            "updated_at": now,
        }
        if baseline:
            update_values["baseline_at"] = now
        if last_error_code is None:
            update_values["last_success_at"] = now

        stmt = (
            insert(HelpdeskImapMailboxState)
            .values(**insert_values)
            .on_conflict_do_update(
                constraint="uq_helpdesk_imap_mailbox_state_folder",
                set_=update_values,
            )
            .returning(HelpdeskImapMailboxState)
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.scalar_one()
