from typing import Any

import pytest
from aiogram.types import Update

from app.bot.routers.business import (
    handle_business_connection,
    handle_business_message,
    handle_deleted_business_messages,
    handle_edited_business_message,
)
from app.core.config import Settings
from app.llm.types import LLMMessage, LLMResponse
from app.services.business_service import (
    BusinessMessageStatus,
    InMemoryBusinessRepository,
)


class FakeBot:
    def __init__(self) -> None:
        self.sent_messages: list[dict[str, Any]] = []

    async def send_message(
        self,
        chat_id: int,
        text: str,
        business_connection_id: str | None = None,
        **kwargs: Any,
    ) -> object:
        self.sent_messages.append(
            {
                "chat_id": chat_id,
                "text": text,
                "business_connection_id": business_connection_id,
            }
        )
        return object()


class WorkingProvider:
    name = "yandex"

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        return LLMResponse(content="Бизнес-ответ.", provider=self.name, model="test-model")

    async def stream(self, messages: list[LLMMessage]):
        yield "unused"

    async def list_models(self) -> list[str]:
        return ["test-model"]


def make_business_connection_update(*, owner_id: int = 100500, can_reply: bool = True) -> Update:
    return Update.model_validate(
        {
            "update_id": 1,
            "business_connection": {
                "id": "bc-1",
                "user": {"id": owner_id, "is_bot": False, "first_name": "Owner"},
                "user_chat_id": owner_id,
                "date": 1_710_000_000,
                "is_enabled": True,
                "can_reply": can_reply,
                "rights": {
                    "can_reply": can_reply,
                    "can_read_messages": True,
                },
            },
        }
    )


def make_business_message_update(*, text: str = "!jarvis ping") -> Update:
    return Update.model_validate(
        {
            "update_id": 2,
            "business_message": {
                "message_id": 7,
                "date": 1_710_000_000,
                "business_connection_id": "bc-1",
                "chat": {"id": 200, "type": "private", "first_name": "Client"},
                "from": {"id": 300, "is_bot": False, "first_name": "Client"},
                "text": text,
            },
        }
    )


def make_edited_business_message_update() -> Update:
    payload = make_business_message_update(text="исправлено").model_dump(exclude_none=True)
    payload["edited_business_message"] = payload.pop("business_message")
    payload["update_id"] = 3
    return Update.model_validate(payload)


def make_deleted_business_messages_update() -> Update:
    return Update.model_validate(
        {
            "update_id": 4,
            "deleted_business_messages": {
                "business_connection_id": "bc-1",
                "chat": {"id": 200, "type": "private", "first_name": "Client"},
                "message_ids": [7, 8],
            },
        }
    )


@pytest.mark.asyncio
async def test_router_handles_business_connection_and_trigger_reply() -> None:
    repository = InMemoryBusinessRepository()
    bot = FakeBot()
    settings = Settings(
        admin_telegram_ids="100500",
        business_mode_enabled=True,
        business_reply_enabled=True,
        business_reply_trigger="!jarvis",
    )
    connection_update = make_business_connection_update()
    message_update = make_business_message_update(text="!jarvis ответь тестово")

    await handle_business_connection(
        connection_update.business_connection,
        bot=bot,
        settings=settings,
        business_repository=repository,
        llm_provider=WorkingProvider(),
    )
    await handle_business_message(
        message_update.business_message,
        bot=bot,
        settings=settings,
        business_repository=repository,
        llm_provider=WorkingProvider(),
    )

    assert bot.sent_messages == [
        {
            "chat_id": 200,
            "text": "Бизнес-ответ.",
            "business_connection_id": "bc-1",
        }
    ]
    assert repository.messages[0].status == BusinessMessageStatus.ANSWERED.value


@pytest.mark.asyncio
async def test_router_does_not_reply_when_can_reply_is_false() -> None:
    repository = InMemoryBusinessRepository()
    bot = FakeBot()
    settings = Settings(
        admin_telegram_ids="100500",
        business_mode_enabled=True,
        business_reply_enabled=True,
    )

    await handle_business_connection(
        make_business_connection_update(can_reply=False).business_connection,
        bot=bot,
        settings=settings,
        business_repository=repository,
        llm_provider=WorkingProvider(),
    )
    await handle_business_message(
        make_business_message_update().business_message,
        bot=bot,
        settings=settings,
        business_repository=repository,
        llm_provider=WorkingProvider(),
    )

    assert bot.sent_messages == []
    assert repository.messages[0].status == BusinessMessageStatus.IGNORED.value


@pytest.mark.asyncio
async def test_router_records_edited_and_deleted_without_reply() -> None:
    repository = InMemoryBusinessRepository()
    bot = FakeBot()
    settings = Settings(business_mode_enabled=True, business_reply_enabled=True)

    await handle_edited_business_message(
        make_edited_business_message_update().edited_business_message,
        bot=bot,
        settings=settings,
        business_repository=repository,
        llm_provider=WorkingProvider(),
    )
    await handle_deleted_business_messages(
        make_deleted_business_messages_update().deleted_business_messages,
        bot=bot,
        settings=settings,
        business_repository=repository,
        llm_provider=WorkingProvider(),
    )

    assert bot.sent_messages == []
    assert [message.status for message in repository.messages] == [
        BusinessMessageStatus.EDITED.value,
        BusinessMessageStatus.DELETED.value,
        BusinessMessageStatus.DELETED.value,
    ]
