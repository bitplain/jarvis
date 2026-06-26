from dataclasses import dataclass
from uuid import uuid4

import pytest

from app.services.household_memory_service import (
    HouseholdMemoryLimitExceeded,
    HouseholdMemorySecretRejected,
    HouseholdMemoryService,
)


@dataclass
class FakeEntry:
    id: str
    scope_type: str
    scope_chat_id: int
    created_by_user_id: int
    text: str
    status: str = "active"


class FakeHouseholdMemoryRepository:
    def __init__(self) -> None:
        self.entries: list[FakeEntry] = []

    async def active_count(self, *, scope_type: str, scope_chat_id: int) -> int:
        return len(
            [
                entry
                for entry in self.entries
                if entry.scope_type == scope_type
                and entry.scope_chat_id == scope_chat_id
                and entry.status == "active"
            ]
        )

    async def create(
        self,
        *,
        scope_type: str,
        scope_chat_id: int,
        created_by_user_id: int,
        text: str,
    ) -> FakeEntry:
        entry = FakeEntry(
            id=uuid4().hex,
            scope_type=scope_type,
            scope_chat_id=scope_chat_id,
            created_by_user_id=created_by_user_id,
            text=text,
        )
        self.entries.append(entry)
        return entry

    async def list_active(self, *, scope_type: str, scope_chat_id: int, limit: int = 100):
        del limit
        return [
            entry
            for entry in self.entries
            if entry.scope_type == scope_type
            and entry.scope_chat_id == scope_chat_id
            and entry.status == "active"
        ]

    async def soft_delete(self, *, memory_id: str, actor_user_id: int):
        del actor_user_id
        for entry in self.entries:
            if entry.id.startswith(memory_id) and entry.status == "active":
                entry.status = "deleted"
                return entry
        return None


@pytest.mark.asyncio
async def test_add_memory_validates_length_and_lists_active_only() -> None:
    repo = FakeHouseholdMemoryRepository()
    service = HouseholdMemoryService(repo, max_text_length=20)

    await service.add_memory("private", 100500, 100500, "семейный чат Фемилис")
    entry = await service.add_memory("private", 100500, 100500, "молоко в список")
    await service.delete_memory_by_id(str(entry.id), actor_user_id=100500)

    assert [memory.text for memory in await service.list_memories("private", 100500)] == [
        "семейный чат Фемилис"
    ]
    with pytest.raises(ValueError, match="empty"):
        await service.add_memory("private", 100500, 100500, "   ")
    with pytest.raises(ValueError, match="too_long"):
        await service.add_memory("private", 100500, 100500, "x" * 21)


@pytest.mark.asyncio
async def test_add_memory_rejects_secret_looking_text() -> None:
    repo = FakeHouseholdMemoryRepository()
    service = HouseholdMemoryService(repo)

    with pytest.raises(HouseholdMemorySecretRejected):
        await service.add_memory("private", 100500, 100500, "api key: secret")
    with pytest.raises(HouseholdMemorySecretRejected):
        await service.add_memory("private", 100500, 100500, "Authorization: Bearer token")


@pytest.mark.asyncio
async def test_max_active_memories_limit() -> None:
    repo = FakeHouseholdMemoryRepository()
    service = HouseholdMemoryService(repo, max_entries_per_scope=1)

    await service.add_memory("group", -100, 100500, "первый факт")

    with pytest.raises(HouseholdMemoryLimitExceeded):
        await service.add_memory("group", -100, 100500, "второй факт")
