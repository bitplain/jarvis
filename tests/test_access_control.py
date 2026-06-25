from typing import Any

import pytest
from aiogram.types import Message

from app.bot.middlewares.access import AdminAccessMiddleware, is_admin_user


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
