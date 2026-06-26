import pytest

from app.db.models import MessageRole
from app.services.memory_service import InMemoryMessageRepository, MemoryService
from app.services.runtime_settings_service import PromptProfile


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


@pytest.mark.asyncio
async def test_private_short_profile_updates_only_system_prompt() -> None:
    repo = InMemoryMessageRepository()
    service = MemoryService(repo, max_messages=2)
    await service.add_message(chat_id=10, user_id=1, role=MessageRole.USER, text="вопрос")

    context = await service.build_context(
        chat_id=10,
        prompt_profile=PromptProfile.SHORT,
        chat_kind="private",
    )

    assert context[0].role == "system"
    assert "Отвечай коротко" in context[0].content
    assert "личном чате" in context[0].content
    assert [message.content for message in context[1:]] == ["вопрос"]


@pytest.mark.asyncio
async def test_group_deep_profile_adds_group_safe_instruction() -> None:
    repo = InMemoryMessageRepository()
    service = MemoryService(repo, max_messages=2)
    await service.add_message(chat_id=-100123, user_id=1, role=MessageRole.USER, text="группа")

    context = await service.build_context(
        chat_id=-100123,
        prompt_profile=PromptProfile.DEEP,
        chat_kind="group",
    )

    assert "Дай подробный разбор" in context[0].content
    assert "групповом чате" in context[0].content
    assert "не делай вид, что видишь всю историю группы" in context[0].content
    assert context[1].content == "группа"


@pytest.mark.asyncio
async def test_custom_raw_prompt_replaces_default_system_prompt() -> None:
    repo = InMemoryMessageRepository()
    service = MemoryService(repo, max_messages=2)
    await service.add_message(chat_id=10, user_id=1, role=MessageRole.USER, text="вопрос")

    context = await service.build_context(
        chat_id=10,
        system_prompt="Ты Jarvis. Это сырой custom prompt для теста.",
    )

    assert context[0].role == "system"
    assert context[0].content == "Ты Jarvis. Это сырой custom prompt для теста."
    assert context[1].content == "вопрос"
