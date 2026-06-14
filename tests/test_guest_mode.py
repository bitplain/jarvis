from typing import Any

import pytest
from aiogram.types import InlineQueryResultArticle, Update

from app.bot.routers.guest import build_guest_answer_result, handle_guest_message
from app.core.config import Settings
from app.llm.types import LLMMessage, LLMResponse
from app.services.guest_service import (
    GUEST_DISABLED_MESSAGE,
    GUEST_EMPTY_TEXT_MESSAGE,
    GUEST_OWNER_ONLY_MESSAGE,
    InMemoryGuestMessageRepository,
)


class FakeBot:
    def __init__(self) -> None:
        self.answers: list[dict[str, Any]] = []

    async def answer_guest_query(self, guest_query_id: str, result: object) -> None:
        self.answers.append({"guest_query_id": guest_query_id, "result": result})


class WorkingProvider:
    name = "yandex"

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        return LLMResponse(content="ответ модели", provider=self.name, model="test-model")

    async def stream(self, messages: list[LLMMessage]):
        yield "unused"

    async def list_models(self) -> list[str]:
        return ["test-model"]


def make_guest_update(
    *,
    text: str | None = "@jarvis_bot сделай кратко",
    guest_query_id: str | None = "guest-query-id",
    caller_user_id: int | None = 100500,
    replied_text: str | None = "текст reply",
) -> Update:
    guest_message: dict[str, Any] = {
        "message_id": 7,
        "date": 1_710_000_000,
        "chat": {"id": -100, "type": "group", "title": "Guest Chat"},
    }
    if text is not None:
        guest_message["text"] = text
    if guest_query_id is not None:
        guest_message["guest_query_id"] = guest_query_id
    if caller_user_id is not None:
        guest_message["guest_bot_caller_user"] = {
            "id": caller_user_id,
            "is_bot": False,
            "first_name": "Admin",
        }
    if replied_text is not None:
        guest_message["reply_to_message"] = {
            "message_id": 6,
            "date": 1_710_000_000,
            "chat": {"id": -100, "type": "group"},
            "text": replied_text,
        }
    return Update.model_validate({"update_id": 77, "guest_message": guest_message})


def answer_text(answer: dict[str, Any]) -> str:
    result = answer["result"]
    assert isinstance(result, InlineQueryResultArticle)
    content = result.input_message_content
    return content.message_text


def test_synthetic_guest_update_is_supported_by_aiogram() -> None:
    update = make_guest_update()

    assert update.event_type == "guest_message"
    assert update.guest_message is not None
    assert update.guest_message.guest_query_id == "guest-query-id"


def test_build_guest_answer_result_returns_typed_article() -> None:
    result = build_guest_answer_result("короткий ответ")

    assert isinstance(result, InlineQueryResultArticle)
    assert result.input_message_content.message_text == "короткий ответ"


@pytest.mark.asyncio
async def test_guest_mode_disabled_answers_safe_refusal() -> None:
    update = make_guest_update()
    repository = InMemoryGuestMessageRepository()
    bot = FakeBot()

    await handle_guest_message(
        update.guest_message,
        bot=bot,
        settings=Settings(admin_telegram_ids="100500", guest_mode_enabled=False),
        event_update=update,
        guest_repository=repository,
        llm_provider=WorkingProvider(),
    )

    assert answer_text(bot.answers[0]) == GUEST_DISABLED_MESSAGE
    assert repository.records[0].status == "ignored"


@pytest.mark.asyncio
async def test_guest_query_without_guest_query_id_is_ignored() -> None:
    update = make_guest_update(guest_query_id=None)
    repository = InMemoryGuestMessageRepository()
    bot = FakeBot()

    await handle_guest_message(
        update.guest_message,
        bot=bot,
        settings=Settings(admin_telegram_ids="100500", guest_mode_enabled=True),
        event_update=update,
        guest_repository=repository,
        llm_provider=WorkingProvider(),
    )

    assert bot.answers == []
    assert repository.records[0].status == "ignored"


@pytest.mark.asyncio
async def test_empty_guest_text_gets_helpful_response() -> None:
    update = make_guest_update(text=None)
    repository = InMemoryGuestMessageRepository()
    bot = FakeBot()

    await handle_guest_message(
        update.guest_message,
        bot=bot,
        settings=Settings(admin_telegram_ids="100500", guest_mode_enabled=True),
        event_update=update,
        guest_repository=repository,
        llm_provider=WorkingProvider(),
    )

    assert answer_text(bot.answers[0]) == GUEST_EMPTY_TEXT_MESSAGE
    assert repository.records[0].status == "answered"


@pytest.mark.asyncio
async def test_unauthorized_guest_caller_is_rejected() -> None:
    update = make_guest_update(caller_user_id=5)
    repository = InMemoryGuestMessageRepository()
    bot = FakeBot()

    await handle_guest_message(
        update.guest_message,
        bot=bot,
        settings=Settings(admin_telegram_ids="100500", guest_mode_enabled=True),
        event_update=update,
        guest_repository=repository,
        llm_provider=WorkingProvider(),
    )

    assert answer_text(bot.answers[0]) == GUEST_OWNER_ONLY_MESSAGE
    assert repository.records[0].status == "ignored"


@pytest.mark.asyncio
async def test_authorized_guest_caller_is_processed_with_replied_text() -> None:
    update = make_guest_update(replied_text="контекст reply")
    repository = InMemoryGuestMessageRepository()
    bot = FakeBot()

    await handle_guest_message(
        update.guest_message,
        bot=bot,
        settings=Settings(
            telegram_bot_username="jarvis_bot",
            admin_telegram_ids="100500",
            guest_mode_enabled=True,
        ),
        event_update=update,
        guest_repository=repository,
        llm_provider=WorkingProvider(),
    )

    assert answer_text(bot.answers[0]) == "ответ модели"
    assert repository.records[0].status == "answered"
    assert repository.records[0].replied_text == "контекст reply"
