import pytest

from app.db.models import MessageRole
from app.services.memory_service import InMemoryMessageRepository, MemoryService


@pytest.mark.asyncio
async def test_memory_keeps_last_n_messages() -> None:
    repo = InMemoryMessageRepository()
    service = MemoryService(repo, max_messages=2)

    await service.add_message(chat_id=10, user_id=1, role=MessageRole.USER, text="one")
    await service.add_message(chat_id=10, user_id=1, role=MessageRole.ASSISTANT, text="two")
    await service.add_message(chat_id=10, user_id=1, role=MessageRole.USER, text="three")

    context = await service.build_context(chat_id=10)

    assert [message.content for message in context] == [
        service.system_prompt,
        "two",
        "three",
    ]


@pytest.mark.asyncio
async def test_reset_clears_memory() -> None:
    repo = InMemoryMessageRepository()
    service = MemoryService(repo, max_messages=5)
    await service.add_message(chat_id=10, user_id=1, role=MessageRole.USER, text="hello")

    await service.reset_chat(chat_id=10)

    assert await service.recent_messages(chat_id=10) == []
