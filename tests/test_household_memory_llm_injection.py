import pytest

from app.db.models import MessageRole
from app.llm.types import LLMMessage
from app.services.memory_service import InMemoryMessageRepository, MemoryService


class FakeHouseholdMemoryService:
    def __init__(self, values: list[str] | Exception) -> None:
        self.values = values
        self.calls: list[tuple[str, int]] = []

    async def list_memory_texts_for_prompt(self, scope_type: str, chat_id: int) -> list[str]:
        self.calls.append((scope_type, chat_id))
        if isinstance(self.values, Exception):
            raise self.values
        return self.values


@pytest.mark.asyncio
async def test_private_household_memory_is_injected_into_system_prompt() -> None:
    repo = InMemoryMessageRepository()
    service = MemoryService(repo, max_messages=5)
    await service.add_message(chat_id=100500, user_id=100500, role=MessageRole.USER, text="вопрос")

    context = await service.build_context(
        chat_id=100500,
        household_memory=FakeHouseholdMemoryService(["у нас семейный чат Фемилис"]),
        household_scope_type="private",
    )

    assert "Память о текущем чате:" in context[0].content
    assert "- у нас семейный чат Фемилис" in context[0].content
    assert context[1:] == [LLMMessage(role="user", content="вопрос")]


@pytest.mark.asyncio
async def test_group_household_memory_uses_group_scope_without_cross_chat_leak() -> None:
    repo = InMemoryMessageRepository()
    service = MemoryService(repo, max_messages=5)
    memory = FakeHouseholdMemoryService(["только эта группа"])

    context = await service.build_context(
        chat_id=-100123,
        household_memory=memory,
        household_scope_type="group",
    )

    assert memory.calls == [("group", -100123)]
    assert "только эта группа" in context[0].content
    assert "другая группа" not in context[0].content


@pytest.mark.asyncio
async def test_household_memory_db_error_does_not_break_llm_context() -> None:
    repo = InMemoryMessageRepository()
    service = MemoryService(repo, max_messages=5)

    context = await service.build_context(
        chat_id=100500,
        household_memory=FakeHouseholdMemoryService(RuntimeError("db down")),
        household_scope_type="private",
    )

    assert context[0].content == service.system_prompt
