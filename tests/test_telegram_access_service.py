import pytest

from app.services.telegram_access_service import (
    AccessEntry,
    TelegramAccessService,
)


class FakeTelegramAccessRepository:
    def __init__(self) -> None:
        self.entries: dict[tuple[str, int], AccessEntry] = {}

    async def get_entry(self, entry_type: str, telegram_id: int) -> AccessEntry | None:
        return self.entries.get((entry_type, telegram_id))

    async def list_entries(self, entry_type: str) -> list[AccessEntry]:
        return [
            entry
            for (stored_type, _), entry in sorted(self.entries.items())
            if stored_type == entry_type
        ]

    async def upsert_entry(
        self,
        *,
        entry_type: str,
        telegram_id: int,
        label: str | None,
        created_by: int | None,
    ) -> None:
        self.entries[(entry_type, telegram_id)] = AccessEntry(
            entry_type=entry_type,
            telegram_id=telegram_id,
            label=label,
            created_by=created_by,
        )

    async def delete_entry(self, entry_type: str, telegram_id: int) -> bool:
        return self.entries.pop((entry_type, telegram_id), None) is not None


@pytest.mark.asyncio
async def test_env_admin_is_admin_and_allowed() -> None:
    service = TelegramAccessService(FakeTelegramAccessRepository(), admin_ids={100500})

    assert service.is_admin_user(100500) is True
    assert await service.is_allowed_user(100500) is True


@pytest.mark.asyncio
async def test_db_allowed_user_is_allowed_but_not_admin() -> None:
    repository = FakeTelegramAccessRepository()
    service = TelegramAccessService(repository, admin_ids={100500})

    await service.add_allowed_user(200600, "Иван", created_by=100500)

    assert service.is_admin_user(200600) is False
    assert await service.is_allowed_user(200600) is True
    assert await service.list_allowed_users() == [
        AccessEntry(entry_type="user", telegram_id=200600, label="Иван", created_by=100500)
    ]


@pytest.mark.asyncio
async def test_unknown_user_is_denied() -> None:
    service = TelegramAccessService(FakeTelegramAccessRepository(), admin_ids={100500})

    assert service.is_admin_user(42) is False
    assert await service.is_allowed_user(42) is False


@pytest.mark.asyncio
async def test_allowed_group_is_stored_listed_and_removed() -> None:
    repository = FakeTelegramAccessRepository()
    service = TelegramAccessService(repository, admin_ids={100500})

    assert await service.is_allowed_group(-100123) is True

    await service.add_allowed_group(-100123, "Домашний чат", created_by=100500)

    assert await service.is_allowed_group(-100123) is True
    assert await service.is_allowed_group(-100999) is False
    assert await service.list_allowed_groups() == [
        AccessEntry(
            entry_type="group",
            telegram_id=-100123,
            label="Домашний чат",
            created_by=100500,
        )
    ]
    assert await service.remove_allowed_group(-100123) is True
    assert await service.is_allowed_group(-100999) is True


@pytest.mark.asyncio
async def test_duplicate_add_is_idempotent_and_safe() -> None:
    service = TelegramAccessService(FakeTelegramAccessRepository(), admin_ids={100500})

    await service.add_allowed_user(200600, "Иван", created_by=100500)
    await service.add_allowed_user(200600, "Иван Петров", created_by=100500)

    assert await service.list_allowed_users() == [
        AccessEntry(
            entry_type="user",
            telegram_id=200600,
            label="Иван Петров",
            created_by=100500,
        )
    ]


@pytest.mark.asyncio
async def test_remove_missing_is_safe() -> None:
    service = TelegramAccessService(FakeTelegramAccessRepository(), admin_ids={100500})

    assert await service.remove_allowed_user(200600) is False


@pytest.mark.asyncio
async def test_invalid_user_ids_are_rejected() -> None:
    service = TelegramAccessService(FakeTelegramAccessRepository(), admin_ids={100500})

    with pytest.raises(ValueError, match="invalid_user_id"):
        await service.add_allowed_user(0, None, created_by=100500)

    with pytest.raises(ValueError, match="invalid_user_id"):
        await service.remove_allowed_user(-42)
