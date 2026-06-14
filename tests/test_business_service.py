import logging
from typing import Any

import pytest

from app.core.config import Settings
from app.llm.base import LLMProviderError
from app.llm.types import LLMMessage, LLMResponse
from app.services.business_service import (
    BusinessConnectionEvent,
    BusinessConnectionStatus,
    BusinessMessageDirection,
    BusinessMessageRequest,
    BusinessMessageStatus,
    BusinessService,
    DeletedBusinessMessagesRequest,
    InMemoryBusinessRepository,
)


class WorkingProvider:
    name = "yandex"

    def __init__(self) -> None:
        self.messages: list[LLMMessage] = []

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        self.messages = messages
        return LLMResponse(content="Сообщение получено.", provider=self.name, model="test-model")

    async def stream(self, messages: list[LLMMessage]):
        yield "unused"

    async def list_models(self) -> list[str]:
        return ["test-model"]


class FailingProvider(WorkingProvider):
    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        raise LLMProviderError("network_error", retryable=True)


class FakeBusinessApi:
    def __init__(self) -> None:
        self.sent_messages: list[dict[str, Any]] = []
        self.lookups: list[str] = []
        self.connection: BusinessConnectionEvent | None = None

    async def get_business_connection(self, business_connection_id: str) -> BusinessConnectionEvent:
        self.lookups.append(business_connection_id)
        if self.connection is None:
            raise RuntimeError("connection not found")
        return self.connection

    async def send_business_message(
        self,
        *,
        business_connection_id: str,
        chat_id: int,
        text: str,
    ) -> None:
        self.sent_messages.append(
            {
                "business_connection_id": business_connection_id,
                "chat_id": chat_id,
                "text": text,
            }
        )


def make_connection(
    *,
    business_connection_id: str = "bc-1",
    business_user_id: int | None = 100500,
    is_enabled: bool = True,
    can_reply: bool = True,
) -> BusinessConnectionEvent:
    return BusinessConnectionEvent(
        business_connection_id=business_connection_id,
        business_user_id=business_user_id,
        user_chat_id=100500,
        is_enabled=is_enabled,
        can_reply=can_reply,
        can_read_messages=True,
        rights_json={"can_reply": can_reply, "can_read_messages": True},
    )


def make_message(
    *,
    text: str = "!jarvis кратко ответь",
    business_connection_id: str = "bc-1",
    chat_id: int = 200,
    telegram_message_id: int = 7,
) -> BusinessMessageRequest:
    return BusinessMessageRequest(
        business_connection_id=business_connection_id,
        telegram_message_id=telegram_message_id,
        chat_id=chat_id,
        from_user_id=300,
        text=text,
        reply_to_message_id=None,
    )


@pytest.mark.asyncio
async def test_business_connection_is_saved_enabled() -> None:
    repository = InMemoryBusinessRepository()
    service = BusinessService(
        Settings(admin_telegram_ids="100500"),
        repository=repository,
        provider=WorkingProvider(),
        business_api=FakeBusinessApi(),
    )

    result = await service.handle_connection(make_connection())

    assert result.status == BusinessConnectionStatus.ENABLED.value
    assert repository.connections["bc-1"].status == BusinessConnectionStatus.ENABLED.value
    assert repository.connections["bc-1"].can_reply is True


@pytest.mark.asyncio
async def test_disabled_business_connection_is_saved_as_disabled() -> None:
    repository = InMemoryBusinessRepository()
    service = BusinessService(
        Settings(admin_telegram_ids="100500"),
        repository=repository,
        provider=WorkingProvider(),
        business_api=FakeBusinessApi(),
    )

    result = await service.handle_connection(make_connection(is_enabled=False))

    assert result.status == BusinessConnectionStatus.DISABLED.value
    assert repository.connections["bc-1"].status == BusinessConnectionStatus.DISABLED.value
    assert repository.connections["bc-1"].disabled_at is not None


@pytest.mark.asyncio
async def test_business_connection_from_non_admin_owner_is_ignored() -> None:
    repository = InMemoryBusinessRepository()
    service = BusinessService(
        Settings(admin_telegram_ids="100500", business_admin_only=True),
        repository=repository,
        provider=WorkingProvider(),
        business_api=FakeBusinessApi(),
    )

    result = await service.handle_connection(make_connection(business_user_id=5))

    assert result.status == BusinessConnectionStatus.IGNORED.value
    assert repository.connections["bc-1"].status == BusinessConnectionStatus.IGNORED.value


@pytest.mark.asyncio
async def test_business_mode_disabled_records_message_without_reply() -> None:
    repository = InMemoryBusinessRepository()
    api = FakeBusinessApi()
    provider = WorkingProvider()
    service = BusinessService(
        Settings(
            admin_telegram_ids="100500",
            business_mode_enabled=False,
            business_reply_enabled=True,
        ),
        repository=repository,
        provider=provider,
        business_api=api,
    )
    await service.handle_connection(make_connection())

    result = await service.handle_business_message(make_message())

    assert result.status == BusinessMessageStatus.IGNORED.value
    assert repository.messages[0].status == BusinessMessageStatus.IGNORED.value
    assert api.sent_messages == []
    assert provider.messages == []


@pytest.mark.asyncio
async def test_can_reply_false_records_message_without_reply() -> None:
    repository = InMemoryBusinessRepository()
    api = FakeBusinessApi()
    provider = WorkingProvider()
    service = BusinessService(
        Settings(
            admin_telegram_ids="100500",
            business_mode_enabled=True,
            business_reply_enabled=True,
        ),
        repository=repository,
        provider=provider,
        business_api=api,
    )
    await service.handle_connection(make_connection(can_reply=False))

    result = await service.handle_business_message(make_message())

    assert result.status == BusinessMessageStatus.IGNORED.value
    assert api.sent_messages == []
    assert provider.messages == []


@pytest.mark.asyncio
async def test_business_reply_disabled_keeps_received_without_reply() -> None:
    repository = InMemoryBusinessRepository()
    api = FakeBusinessApi()
    provider = WorkingProvider()
    service = BusinessService(
        Settings(
            admin_telegram_ids="100500",
            business_mode_enabled=True,
            business_reply_enabled=False,
        ),
        repository=repository,
        provider=provider,
        business_api=api,
    )
    await service.handle_connection(make_connection())

    result = await service.handle_business_message(make_message())

    assert result.status == BusinessMessageStatus.RECEIVED.value
    assert api.sent_messages == []
    assert provider.messages == []


@pytest.mark.asyncio
async def test_business_message_without_trigger_does_not_reply() -> None:
    repository = InMemoryBusinessRepository()
    api = FakeBusinessApi()
    provider = WorkingProvider()
    service = BusinessService(
        Settings(
            admin_telegram_ids="100500",
            business_mode_enabled=True,
            business_reply_enabled=True,
            business_reply_trigger="!jarvis",
        ),
        repository=repository,
        provider=provider,
        business_api=api,
    )
    await service.handle_connection(make_connection())

    result = await service.handle_business_message(make_message(text="привет"))

    assert result.status == BusinessMessageStatus.RECEIVED.value
    assert api.sent_messages == []
    assert provider.messages == []


@pytest.mark.asyncio
async def test_business_message_with_trigger_calls_llm_and_sends_business_reply() -> None:
    repository = InMemoryBusinessRepository()
    api = FakeBusinessApi()
    provider = WorkingProvider()
    service = BusinessService(
        Settings(
            admin_telegram_ids="100500",
            business_mode_enabled=True,
            business_reply_enabled=True,
            business_reply_trigger="!jarvis",
        ),
        repository=repository,
        provider=provider,
        business_api=api,
    )
    await service.handle_connection(make_connection())

    result = await service.handle_business_message(
        make_message(text="!jarvis кратко ответь, что сообщение получено")
    )

    rendered_prompt = "\n".join(message.content for message in provider.messages)
    assert result.status == BusinessMessageStatus.ANSWERED.value
    assert "кратко ответь, что сообщение получено" in rendered_prompt
    assert "!jarvis" not in rendered_prompt
    assert api.sent_messages == [
        {
            "business_connection_id": "bc-1",
            "chat_id": 200,
            "text": "Сообщение получено.",
        }
    ]
    assert repository.messages[0].status == BusinessMessageStatus.ANSWERED.value
    assert repository.messages[1].direction == BusinessMessageDirection.OUTGOING.value


@pytest.mark.asyncio
async def test_missing_connection_is_looked_up_before_reply() -> None:
    repository = InMemoryBusinessRepository()
    api = FakeBusinessApi()
    api.connection = make_connection()
    service = BusinessService(
        Settings(
            admin_telegram_ids="100500",
            business_mode_enabled=True,
            business_reply_enabled=False,
        ),
        repository=repository,
        provider=WorkingProvider(),
        business_api=api,
    )

    result = await service.handle_business_message(make_message())

    assert api.lookups == ["bc-1"]
    assert result.status == BusinessMessageStatus.RECEIVED.value
    assert repository.connections["bc-1"].status == BusinessConnectionStatus.ENABLED.value


@pytest.mark.asyncio
async def test_failed_connection_lookup_marks_message_failed() -> None:
    repository = InMemoryBusinessRepository()
    service = BusinessService(
        Settings(business_mode_enabled=True, business_reply_enabled=True),
        repository=repository,
        provider=WorkingProvider(),
        business_api=FakeBusinessApi(),
    )

    result = await service.handle_business_message(make_message())

    assert result.status == BusinessMessageStatus.FAILED.value
    assert repository.messages[0].error_code == "connection_lookup_failed"


@pytest.mark.asyncio
async def test_edited_business_message_is_recorded_without_reply() -> None:
    repository = InMemoryBusinessRepository()
    api = FakeBusinessApi()
    service = BusinessService(
        Settings(business_mode_enabled=True, business_reply_enabled=True),
        repository=repository,
        provider=WorkingProvider(),
        business_api=api,
    )

    result = await service.handle_edited_business_message(make_message(text="исправлено"))

    assert result.status == BusinessMessageStatus.EDITED.value
    assert repository.messages[0].direction == BusinessMessageDirection.EDITED.value
    assert api.sent_messages == []


@pytest.mark.asyncio
async def test_deleted_business_messages_are_recorded_without_reply() -> None:
    repository = InMemoryBusinessRepository()
    api = FakeBusinessApi()
    service = BusinessService(
        Settings(business_mode_enabled=True, business_reply_enabled=True),
        repository=repository,
        provider=WorkingProvider(),
        business_api=api,
    )

    result = await service.handle_deleted_business_messages(
        DeletedBusinessMessagesRequest(
            business_connection_id="bc-1",
            chat_id=200,
            message_ids=[7, 8],
        )
    )

    assert result.status == BusinessMessageStatus.DELETED.value
    assert [message.direction for message in repository.messages] == [
        BusinessMessageDirection.DELETED.value,
        BusinessMessageDirection.DELETED.value,
    ]
    assert api.sent_messages == []


@pytest.mark.asyncio
async def test_business_memory_is_separate_from_regular_chat_memory() -> None:
    repository = InMemoryBusinessRepository()
    api = FakeBusinessApi()
    provider = WorkingProvider()
    service = BusinessService(
        Settings(
            admin_telegram_ids="100500",
            business_mode_enabled=True,
            business_reply_enabled=True,
            business_memory_max_messages=2,
        ),
        repository=repository,
        provider=provider,
        business_api=api,
    )
    await service.handle_connection(make_connection())
    await service.handle_business_message(make_message(text="!jarvis первый бизнес текст"))
    await service.handle_business_message(
        make_message(text="!jarvis второй бизнес текст", telegram_message_id=8)
    )

    rendered_prompt = "\n".join(message.content for message in provider.messages)
    assert "первый бизнес текст" in rendered_prompt
    assert "старая память обычного чата" not in rendered_prompt


@pytest.mark.asyncio
async def test_business_logs_do_not_include_secrets(caplog: pytest.LogCaptureFixture) -> None:
    repository = InMemoryBusinessRepository()
    service = BusinessService(
        Settings(
            telegram_bot_token="123456:secret-token",
            openrouter_api_key="openrouter-secret",
            business_mode_enabled=True,
            business_reply_enabled=True,
        ),
        repository=repository,
        provider=FailingProvider(),
        business_api=FakeBusinessApi(),
    )
    await service.handle_connection(make_connection())

    with caplog.at_level(logging.WARNING):
        await service.handle_business_message(
            make_message(text="!jarvis Authorization: Bearer secret-token")
        )

    assert "secret-token" not in caplog.text
    assert "openrouter-secret" not in caplog.text
    assert "Authorization" not in caplog.text
