from dataclasses import dataclass
from typing import Protocol

from app.db.models import TelegramAccessEntryType


class TelegramAccessUnavailable(Exception):
    pass


@dataclass(frozen=True)
class AccessEntry:
    entry_type: str
    telegram_id: int
    label: str | None = None
    created_by: int | None = None


class TelegramAccessRepositoryProtocol(Protocol):
    async def get_entry(self, entry_type: str, telegram_id: int) -> AccessEntry | None:
        raise NotImplementedError

    async def list_entries(self, entry_type: str) -> list[AccessEntry]:
        raise NotImplementedError

    async def upsert_entry(
        self,
        *,
        entry_type: str,
        telegram_id: int,
        label: str | None,
        created_by: int | None,
    ) -> None:
        raise NotImplementedError

    async def delete_entry(self, entry_type: str, telegram_id: int) -> bool:
        raise NotImplementedError


class TelegramAccessService:
    def __init__(
        self,
        repository: TelegramAccessRepositoryProtocol,
        *,
        admin_ids: set[int],
    ) -> None:
        self.repository = repository
        self.admin_ids = admin_ids

    def is_admin_user(self, user_id: int | None) -> bool:
        return user_id is not None and user_id in self.admin_ids

    async def is_allowed_user(self, user_id: int | None) -> bool:
        if user_id is None:
            return False
        if self.is_admin_user(user_id):
            return True
        entry = await self.repository.get_entry(TelegramAccessEntryType.USER.value, user_id)
        return entry is not None

    async def is_allowed_group(self, chat_id: int) -> bool:
        entries = await self.list_allowed_groups()
        if not entries:
            return True
        return any(entry.telegram_id == chat_id for entry in entries)

    async def list_allowed_users(self) -> list[AccessEntry]:
        return await self.repository.list_entries(TelegramAccessEntryType.USER.value)

    async def list_allowed_groups(self) -> list[AccessEntry]:
        return await self.repository.list_entries(TelegramAccessEntryType.GROUP.value)

    async def add_allowed_user(
        self,
        user_id: int,
        label: str | None,
        *,
        created_by: int | None,
    ) -> None:
        _validate_user_id(user_id)
        await self.repository.upsert_entry(
            entry_type=TelegramAccessEntryType.USER.value,
            telegram_id=user_id,
            label=_normalize_label(label),
            created_by=created_by,
        )

    async def remove_allowed_user(self, user_id: int) -> bool:
        _validate_user_id(user_id)
        return await self.repository.delete_entry(TelegramAccessEntryType.USER.value, user_id)

    async def add_allowed_group(
        self,
        chat_id: int,
        label: str | None,
        *,
        created_by: int | None,
    ) -> None:
        await self.repository.upsert_entry(
            entry_type=TelegramAccessEntryType.GROUP.value,
            telegram_id=chat_id,
            label=_normalize_label(label),
            created_by=created_by,
        )

    async def remove_allowed_group(self, chat_id: int) -> bool:
        return await self.repository.delete_entry(TelegramAccessEntryType.GROUP.value, chat_id)


def _validate_user_id(user_id: int) -> None:
    if user_id <= 0:
        raise ValueError("invalid_user_id")


def _normalize_label(label: str | None) -> str | None:
    if label is None:
        return None
    normalized = label.strip()
    return normalized or None
