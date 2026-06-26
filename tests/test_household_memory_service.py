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


@pytest.mark.asyncio
async def test_delete_memory_by_text_matches_live_filler_and_connector_words() -> None:
    repo = FakeHouseholdMemoryRepository()
    service = HouseholdMemoryService(repo)
    await service.add_memory("private", 100500, 100500, "Я Александр системный администратор")

    deleted = await service.delete_memory_by_text(
        "private",
        100500,
        "что я Александр и системный администратор",
        actor_user_id=100500,
    )

    assert [entry.text for entry in deleted] == ["Я Александр системный администратор"]
    assert await service.list_memories("private", 100500) == []


@pytest.mark.asyncio
async def test_delete_memory_by_text_matches_case_insensitive_phrase() -> None:
    repo = FakeHouseholdMemoryRepository()
    service = HouseholdMemoryService(repo)
    await service.add_memory("private", 100500, 100500, "Я Александр системный администратор")

    deleted = await service.delete_memory_by_text(
        "private",
        100500,
        "я александр системный администратор",
        actor_user_id=100500,
    )

    assert [entry.text for entry in deleted] == ["Я Александр системный администратор"]
    assert await service.list_memory_texts_for_prompt("private", 100500) == []


@pytest.mark.asyncio
async def test_delete_memory_by_text_exact_match_works() -> None:
    repo = FakeHouseholdMemoryRepository()
    service = HouseholdMemoryService(repo)
    await service.add_memory("private", 100500, 100500, "у нас семейный чат Фемилис")

    deleted = await service.delete_memory_by_text(
        "private",
        100500,
        "у нас семейный чат Фемилис",
        actor_user_id=100500,
    )

    assert [entry.text for entry in deleted] == ["у нас семейный чат Фемилис"]
    assert await service.list_memories("private", 100500) == []


@pytest.mark.asyncio
async def test_delete_memory_by_text_multiple_matches_returns_choice_without_deleting() -> None:
    repo = FakeHouseholdMemoryRepository()
    service = HouseholdMemoryService(repo)
    await service.add_memory("private", 100500, 100500, "Александр системный администратор")
    await service.add_memory("private", 100500, 100500, "Александр любит короткие отчёты")

    matches = await service.delete_memory_by_text(
        "private",
        100500,
        "Александр",
        actor_user_id=100500,
    )

    assert [entry.text for entry in matches] == [
        "Александр системный администратор",
        "Александр любит короткие отчёты",
    ]
    assert [entry.text for entry in await service.list_memories("private", 100500)] == [
        "Александр системный администратор",
        "Александр любит короткие отчёты",
    ]


@pytest.mark.asyncio
async def test_delete_memory_by_number_uses_current_scope_order() -> None:
    repo = FakeHouseholdMemoryRepository()
    service = HouseholdMemoryService(repo)
    await service.add_memory("private", 100500, 100500, "первый факт")
    await service.add_memory("private", 100500, 100500, "второй факт")

    deleted = await service.delete_memory_by_number(
        "private",
        100500,
        2,
        actor_user_id=100500,
    )

    assert deleted is not None
    assert deleted.text == "второй факт"
    assert [entry.text for entry in await service.list_memories("private", 100500)] == [
        "первый факт"
    ]


@pytest.mark.asyncio
async def test_delete_memory_by_number_invalid_and_repeated_delete_are_safe() -> None:
    repo = FakeHouseholdMemoryRepository()
    service = HouseholdMemoryService(repo)
    await service.add_memory("private", 100500, 100500, "первый факт")

    assert await service.delete_memory_by_number("private", 100500, 2, actor_user_id=100500) is None
    deleted = await service.delete_memory_by_number("private", 100500, 1, actor_user_id=100500)
    assert deleted is not None
    assert await service.delete_memory_by_number("private", 100500, 1, actor_user_id=100500) is None


@pytest.mark.asyncio
async def test_delete_memory_respects_private_and_group_scopes() -> None:
    repo = FakeHouseholdMemoryRepository()
    service = HouseholdMemoryService(repo)
    await service.add_memory("private", 100500, 100500, "общий факт")
    await service.add_memory("group", -1001, 100500, "общий факт")
    await service.add_memory("group", -1002, 100500, "общий факт")

    deleted = await service.delete_memory_by_text(
        "group",
        -1001,
        "общий факт",
        actor_user_id=100500,
    )

    assert [entry.text for entry in deleted] == ["общий факт"]
    assert [entry.text for entry in await service.list_memories("private", 100500)] == [
        "общий факт"
    ]
    assert await service.list_memories("group", -1001) == []
    assert [entry.text for entry in await service.list_memories("group", -1002)] == ["общий факт"]


@pytest.mark.asyncio
async def test_delete_memory_by_id_in_scope_does_not_cross_delete_other_scope() -> None:
    repo = FakeHouseholdMemoryRepository()
    service = HouseholdMemoryService(repo)
    group_entry = await service.add_memory("group", -1001, 100500, "групповой факт")

    deleted = await service.delete_memory_by_id_in_scope(
        "private",
        100500,
        str(group_entry.id),
        actor_user_id=100500,
    )

    assert deleted is None
    assert [entry.text for entry in await service.list_memories("group", -1001)] == [
        "групповой факт"
    ]
