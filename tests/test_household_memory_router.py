from typing import Any

import pytest

from app.bot.routers.household_memory import (
    HouseholdMemoryInput,
    handle_household_memory_callback,
    handle_household_memory_input_message,
    handle_household_memory_message,
    parse_memory_intent,
)
from app.core.config import Settings


class FakeState:
    def __init__(self) -> None:
        self.state: str | None = None
        self.data: dict[str, Any] = {}
        self.cleared = False

    async def set_state(self, state: Any) -> None:
        self.state = getattr(state, "state", str(state))

    async def update_data(self, **kwargs: Any) -> None:
        self.data.update(kwargs)

    async def get_data(self) -> dict[str, Any]:
        return self.data

    async def clear(self) -> None:
        self.state = None
        self.data = {}
        self.cleared = True


class FakeMessage:
    def __init__(
        self,
        text: str,
        *,
        user_id: int = 100500,
        chat_id: int = 100500,
        chat_type: str = "private",
    ) -> None:
        self.text = text
        self.caption = None
        self.message_id = 10
        self.from_user = type("User", (), {"id": user_id})()
        self.chat = type("Chat", (), {"id": chat_id, "type": chat_type})()
        self.answers: list[dict[str, Any]] = []

    async def answer(self, text: str, **kwargs: Any) -> None:
        self.answers.append({"text": text, **kwargs})


class FakeCallback:
    def __init__(
        self,
        data: str = "mem:add",
        *,
        user_id: int = 100500,
        chat_id: int = 100500,
        chat_type: str = "private",
    ) -> None:
        self.data = data
        self.from_user = type("User", (), {"id": user_id})()
        self.message = FakeMessage(
            "callback",
            user_id=user_id,
            chat_id=chat_id,
            chat_type=chat_type,
        )
        self.answers: list[dict[str, Any]] = []

    async def answer(self, text: str | None = None, **kwargs: Any) -> None:
        self.answers.append({"text": text, **kwargs})


class FakeMemoryService:
    def __init__(self) -> None:
        self.added: list[tuple[str, int, int, str]] = []
        self.deleted_texts: list[str] = []
        self.memories = []

    async def add_memory(self, scope_type: str, chat_id: int, user_id: int, text: str):
        self.added.append((scope_type, chat_id, user_id, text))
        return object()

    async def list_memories(self, scope_type: str, chat_id: int):
        del scope_type, chat_id
        return self.memories

    async def delete_memory_by_text(
        self,
        scope_type: str,
        chat_id: int,
        text: str,
        actor_user_id: int,
    ):
        del scope_type, chat_id, actor_user_id
        self.deleted_texts.append(text)
        return []

    async def delete_memory_by_id(self, memory_id: str, actor_user_id: int):
        del memory_id, actor_user_id
        self.deleted_texts.append("by_id")
        return object()


class FakeTelegramAccessService:
    def __init__(self, repository: object, *, admin_ids: set[int]) -> None:
        del repository, admin_ids

    async def is_allowed_user(self, user_id: int | None) -> bool:
        del user_id
        return False

    async def is_allowed_group(self, group_id: int) -> bool:
        del group_id
        return False


def test_parse_memory_intents() -> None:
    assert parse_memory_intent("запомни: у нас семейный чат Фемилис").action == "add"
    assert parse_memory_intent("запомни что молоко обычно добавлять в список").text == (
        "молоко обычно добавлять в список"
    )
    assert parse_memory_intent("что ты помнишь?").action == "list"
    assert parse_memory_intent("забудь: у нас семейный чат Фемилис").action == "delete"
    assert parse_memory_intent("обычный вопрос") is None


@pytest.mark.asyncio
async def test_private_memory_add_does_not_enqueue_llm() -> None:
    message = FakeMessage("запомни: у нас семейный чат Фемилис")
    service = FakeMemoryService()
    redis = type("Redis", (), {"jobs": []})()

    await handle_household_memory_message(
        message,  # type: ignore[arg-type]
        household_memory_intent=parse_memory_intent(message.text),
        household_memory_scope="private",
        household_memory_chat_id=message.chat.id,
        household_memory_service=service,
        redis=redis,
    )

    assert service.added == [("private", 100500, 100500, "у нас семейный чат Фемилис")]
    assert "Сохранил." in message.answers[0]["text"]
    assert redis.jobs == []


@pytest.mark.asyncio
async def test_memory_add_button_fsm_saves_text_and_clears_state() -> None:
    callback = FakeCallback("mem:add")
    state = FakeState()

    await handle_household_memory_callback(
        callback,
        state=state,  # type: ignore[arg-type]
        db_session=object(),
        settings=Settings(admin_telegram_ids="100500"),
    )

    assert state.state == HouseholdMemoryInput.add.state
    assert "Что запомнить?" in callback.message.answers[0]["text"]

    message = FakeMessage("молоко обычно добавлять в список")
    service = FakeMemoryService()
    await handle_household_memory_input_message(
        message,  # type: ignore[arg-type]
        state,  # type: ignore[arg-type]
        household_memory_service=service,
    )

    assert service.added == [("private", 100500, 100500, "молоко обычно добавлять в список")]
    assert state.cleared is True


@pytest.mark.asyncio
async def test_memory_cancel_does_not_save_or_enqueue() -> None:
    state = FakeState()
    await state.set_state(HouseholdMemoryInput.add)
    message = FakeMessage("/cancel")
    service = FakeMemoryService()

    await handle_household_memory_input_message(
        message,  # type: ignore[arg-type]
        state,  # type: ignore[arg-type]
        household_memory_service=service,
    )

    assert service.added == []
    assert message.answers == [{"text": "Ввод отменён."}]


@pytest.mark.asyncio
async def test_group_memory_callback_from_unknown_user_is_silent_and_does_not_mutate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.bot.routers import household_memory

    monkeypatch.setattr(household_memory, "TelegramAccessService", FakeTelegramAccessService)
    callback = FakeCallback("mem:del:abc", user_id=200600, chat_id=-100123, chat_type="group")
    state = FakeState()
    service = FakeMemoryService()

    await handle_household_memory_callback(
        callback,  # type: ignore[arg-type]
        state=state,  # type: ignore[arg-type]
        household_memory_service=service,
        db_session=object(),
        settings=Settings(admin_telegram_ids="100500"),
    )

    assert callback.answers == [{"text": None}]
    assert service.deleted_texts == []
