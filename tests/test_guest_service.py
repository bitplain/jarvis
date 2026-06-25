import logging

import pytest

from app.core.config import Settings
from app.llm.base import LLMProviderError
from app.llm.types import LLMMessage, LLMResponse
from app.services.guest_service import (
    GUEST_LLM_ERROR_MESSAGE,
    GUEST_OWNER_ONLY_MESSAGE,
    GuestRequest,
    GuestService,
    InMemoryGuestMessageRepository,
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
        assert max_tokens == 512
        return LLMResponse(content="готовый ответ", provider=self.name, model="test-model")

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


def make_request(
    *,
    text: str = "@jarvis_bot перескажи это",
    replied_text: str | None = "длинный контекст",
    caller_user_id: int | None = 100500,
) -> GuestRequest:
    return GuestRequest(
        telegram_update_id=77,
        guest_query_id="guest-secret-id",
        caller_user_id=caller_user_id,
        caller_chat_id=-100,
        request_text=text,
        replied_text=replied_text,
    )


@pytest.mark.asyncio
async def test_guest_prompt_uses_only_guest_text_and_replied_text() -> None:
    repository = InMemoryGuestMessageRepository()
    provider = WorkingProvider()
    service = GuestService(
        Settings(
            telegram_bot_username="jarvis_bot",
            admin_telegram_ids="100500",
            guest_mode_enabled=True,
        ),
        repository=repository,
        provider=provider,
    )

    result = await service.handle(make_request())

    rendered_prompt = "\n".join(message.content for message in provider.messages)
    assert result.text == "готовый ответ"
    assert "перескажи это" in rendered_prompt
    assert "длинный контекст" in rendered_prompt
    assert "@jarvis_bot" not in rendered_prompt
    assert "старая память обычного чата" not in rendered_prompt
    assert repository.records[0].status == "answered"
    assert repository.records[0].provider == "yandex"
    assert repository.records[0].model == "test-model"


@pytest.mark.asyncio
async def test_guest_service_without_replied_context_is_honest_in_prompt() -> None:
    repository = InMemoryGuestMessageRepository()
    provider = WorkingProvider()
    service = GuestService(
        Settings(
            telegram_bot_username="jarvis_bot",
            admin_telegram_ids="100500",
            guest_mode_enabled=True,
        ),
        repository=repository,
        provider=provider,
    )

    await service.handle(make_request(text="@jarvis_bot что выше?", replied_text=None))

    rendered_prompt = "\n".join(message.content for message in provider.messages)
    assert "если пользователь просит" in rendered_prompt.lower()
    assert "контекста не видно" in rendered_prompt.lower()


@pytest.mark.asyncio
async def test_guest_service_rejects_unauthorized_caller() -> None:
    repository = InMemoryGuestMessageRepository()
    provider = WorkingProvider()
    service = GuestService(
        Settings(admin_telegram_ids="100500", guest_mode_enabled=True),
        repository=repository,
        provider=provider,
    )

    result = await service.handle(make_request(caller_user_id=None))

    assert result.text == GUEST_OWNER_ONLY_MESSAGE
    assert repository.records[0].status == "ignored"
    assert provider.messages == []


@pytest.mark.asyncio
async def test_guest_service_records_failed_llm_safely() -> None:
    repository = InMemoryGuestMessageRepository()
    service = GuestService(
        Settings(admin_telegram_ids="100500", guest_mode_enabled=True),
        repository=repository,
        provider=FailingProvider(),
    )

    result = await service.handle(make_request())

    assert result.text == GUEST_LLM_ERROR_MESSAGE
    assert repository.records[0].status == "failed"
    assert repository.records[0].error_code == "network_error"


@pytest.mark.asyncio
async def test_guest_service_logs_do_not_include_secrets(caplog: pytest.LogCaptureFixture) -> None:
    repository = InMemoryGuestMessageRepository()
    service = GuestService(
        Settings(
            telegram_bot_token="123456:secret-token",
            openrouter_api_key="openrouter-secret",
            admin_telegram_ids="100500",
            guest_mode_enabled=True,
        ),
        repository=repository,
        provider=FailingProvider(),
    )

    with caplog.at_level(logging.WARNING):
        await service.handle(make_request(text="Authorization header Bearer secret-token"))

    assert "secret-token" not in caplog.text
    assert "openrouter-secret" not in caplog.text
    assert "Authorization" not in caplog.text
