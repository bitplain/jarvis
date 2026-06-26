from typing import Any

import pytest
from aiogram.types import Message

from app.bot.middlewares import access
from app.bot.middlewares.access import AdminAccessMiddleware, is_admin_user
from app.core.config import Settings


def build_message(*, user_id: int, chat_id: int, chat_type: str, text: str = "текст") -> Message:
    return Message.model_validate(
        {
            "message_id": 1,
            "date": 0,
            "chat": {"id": chat_id, "type": chat_type},
            "from": {"id": user_id, "is_bot": False, "first_name": "User"},
            "text": text,
        }
    )


def test_unauthorized_telegram_user_rejected() -> None:
    assert is_admin_user(99, {1, 2}) is False


def test_authorized_telegram_user_accepted() -> None:
    assert is_admin_user(1, {1, 2}) is True


@pytest.mark.asyncio
async def test_private_unauthorized_gets_access_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    middleware = AdminAccessMiddleware({1})
    message = build_message(user_id=99, chat_id=99, chat_type="private")
    answers: list[str] = []
    handler_calls = 0

    async def answer(self: Message, text: str) -> None:
        del self
        answers.append(text)

    monkeypatch.setattr(Message, "answer", answer)

    async def handler(event: object, data: dict[str, Any]) -> None:
        del event, data
        nonlocal handler_calls
        handler_calls += 1

    await middleware(handler, message, {})  # type: ignore[arg-type]

    assert answers == ["Доступ запрещён."]
    assert handler_calls == 0


@pytest.mark.asyncio
async def test_group_unauthorized_is_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    middleware = AdminAccessMiddleware({1})
    message = build_message(user_id=99, chat_id=-100, chat_type="group")
    answers: list[str] = []
    handler_calls = 0

    async def answer(self: Message, text: str) -> None:
        del self
        answers.append(text)

    monkeypatch.setattr(Message, "answer", answer)

    async def handler(event: object, data: dict[str, Any]) -> None:
        del event, data
        nonlocal handler_calls
        handler_calls += 1

    await middleware(handler, message, {})  # type: ignore[arg-type]

    assert answers == []
    assert handler_calls == 0


@pytest.mark.asyncio
async def test_group_unauthorized_mention_is_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    middleware = AdminAccessMiddleware({1})
    message = build_message(
        user_id=99,
        chat_id=-100,
        chat_type="supergroup",
        text="@jarvis_bot вопрос",
    )
    answers: list[str] = []
    handler_calls = 0

    async def answer(self: Message, text: str) -> None:
        del self
        answers.append(text)

    monkeypatch.setattr(Message, "answer", answer)

    async def handler(event: object, data: dict[str, Any]) -> None:
        del event, data
        nonlocal handler_calls
        handler_calls += 1

    await middleware(handler, message, {})  # type: ignore[arg-type]

    assert answers == []
    assert handler_calls == 0


@pytest.mark.asyncio
async def test_private_db_allowed_user_reaches_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeAccessService:
        def __init__(self, repository: object, *, admin_ids: set[int]) -> None:
            del repository, admin_ids

        def is_admin_user(self, user_id: int | None) -> bool:
            return user_id == 1

        async def is_allowed_user(self, user_id: int | None) -> bool:
            return user_id == 99

    monkeypatch.setattr(access, "TelegramAccessRepository", lambda session: object())
    monkeypatch.setattr(access, "TelegramAccessService", FakeAccessService)

    middleware = AdminAccessMiddleware({1})
    message = build_message(user_id=99, chat_id=99, chat_type="private")
    handler_calls = 0

    async def handler(event: object, data: dict[str, Any]) -> None:
        del event, data
        nonlocal handler_calls
        handler_calls += 1

    await middleware(  # type: ignore[arg-type]
        handler,
        message,
        {"db_session": object(), "settings": Settings(telegram_bot_username="jarvis_bot")},
    )

    assert handler_calls == 1


@pytest.mark.asyncio
async def test_group_allowed_user_in_allowed_group_reaches_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeAccessService:
        def __init__(self, repository: object, *, admin_ids: set[int]) -> None:
            del repository, admin_ids

        def is_admin_user(self, user_id: int | None) -> bool:
            return user_id == 1

        async def is_allowed_user(self, user_id: int | None) -> bool:
            return user_id == 99

        async def is_allowed_group(self, chat_id: int) -> bool:
            return chat_id == -100

        async def list_allowed_groups(self) -> list[Any]:
            return [type("Entry", (), {"telegram_id": -100})()]

    monkeypatch.setattr(access, "TelegramAccessRepository", lambda session: object())
    monkeypatch.setattr(access, "TelegramAccessService", FakeAccessService)

    middleware = AdminAccessMiddleware({1})
    message = build_message(
        user_id=99,
        chat_id=-100,
        chat_type="supergroup",
        text="@jarvis_bot вопрос",
    )
    handler_calls = 0

    async def handler(event: object, data: dict[str, Any]) -> None:
        del event, data
        nonlocal handler_calls
        handler_calls += 1

    await middleware(  # type: ignore[arg-type]
        handler,
        message,
        {"db_session": object(), "settings": Settings(telegram_bot_username="jarvis_bot")},
    )

    assert handler_calls == 1


@pytest.mark.asyncio
async def test_group_allowed_user_outside_allowed_group_is_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeAccessService:
        def __init__(self, repository: object, *, admin_ids: set[int]) -> None:
            del repository, admin_ids

        def is_admin_user(self, user_id: int | None) -> bool:
            return user_id == 1

        async def is_allowed_user(self, user_id: int | None) -> bool:
            return user_id == 99

        async def is_allowed_group(self, chat_id: int) -> bool:
            del chat_id
            return False

        async def list_allowed_groups(self) -> list[Any]:
            return [type("Entry", (), {"telegram_id": -100})()]

    monkeypatch.setattr(access, "TelegramAccessRepository", lambda session: object())
    monkeypatch.setattr(access, "TelegramAccessService", FakeAccessService)

    middleware = AdminAccessMiddleware({1})
    message = build_message(
        user_id=99,
        chat_id=-200,
        chat_type="group",
        text="@jarvis_bot вопрос",
    )
    handler_calls = 0

    async def handler(event: object, data: dict[str, Any]) -> None:
        del event, data
        nonlocal handler_calls
        handler_calls += 1

    await middleware(handler, message, {"db_session": object()})  # type: ignore[arg-type]

    assert handler_calls == 0


@pytest.mark.asyncio
async def test_whoami_bypasses_access_middleware_for_id_discovery() -> None:
    middleware = AdminAccessMiddleware({1})
    message = build_message(user_id=99, chat_id=99, chat_type="private", text="/whoami")
    handler_calls = 0

    async def handler(event: object, data: dict[str, Any]) -> None:
        del event, data
        nonlocal handler_calls
        handler_calls += 1

    await middleware(handler, message, {})  # type: ignore[arg-type]

    assert handler_calls == 1
