import logging

import pytest

from app.bot.streaming.text_limits import TELEGRAM_TEXT_LIMIT
from app.core.config import Settings
from app.llm.base import LLMProviderError
from app.llm.types import LLMMessage, LLMResponse, LLMStreamChunk
from app.services.runtime_settings_service import (
    DEFAULT_PROMPTS,
    ActiveLLMProvider,
    PromptProfile,
    PromptProfileScope,
    PromptSetting,
    PromptSource,
)
from app.workers import jobs
from app.workers.jobs import process_llm_message


class FakeBot:
    instances: list["FakeBot"] = []

    def __init__(self, token: str) -> None:
        self.token = token
        self.sent_messages: list[dict[str, object]] = []
        self.chat_actions: list[dict[str, object]] = []
        self.edits: list[dict[str, object]] = []
        self.drafts: list[dict[str, object]] = []
        self.session = self
        self.closed = False
        self.fail_draft = False
        self.__class__.instances.append(self)

    async def send_message_draft(self, **kwargs: object) -> None:
        if self.fail_draft:
            raise RuntimeError("draft unavailable")
        self.drafts.append(kwargs)

    async def send_chat_action(self, **kwargs: object) -> None:
        self.chat_actions.append(kwargs)

    async def send_message(self, **kwargs: object) -> object:
        self.sent_messages.append(kwargs)
        return type("FakeTelegramMessage", (), {"message_id": 77})()

    async def edit_message_text(self, **kwargs: object) -> None:
        self.edits.append(kwargs)

    async def close(self) -> None:
        self.closed = True


class FakeProvider:
    def __init__(self, chunks: list[str] | None = None, complete_text: str = "final") -> None:
        self.chunks = chunks or []
        self.complete_text = complete_text
        self.complete_called = False
        self.stream_called = False

    async def complete(self, messages: list[LLMMessage]) -> LLMResponse:
        del messages
        self.complete_called = True
        return LLMResponse(content=self.complete_text, provider="test", model="test")

    async def stream(self, messages: list[LLMMessage]):
        del messages
        self.stream_called = True
        for chunk in self.chunks:
            yield LLMStreamChunk(content=chunk, provider="test", model="test")


class StreamErrorProvider(FakeProvider):
    async def stream(self, messages: list[LLMMessage]):
        del messages
        self.stream_called = True
        raise LLMProviderError("stream_unavailable", retryable=True)
        yield LLMStreamChunk(content="", provider="test", model="test")


class FakeMemoryService:
    instances: list["FakeMemoryService"] = []

    def __init__(self, repository: object, *, max_messages: int) -> None:
        del repository, max_messages
        self.added: list[dict[str, object]] = []
        self.__class__.instances.append(self)

    async def build_context(
        self,
        *,
        chat_id: int,
        system_prompt: str | None = None,
        prompt_profile: PromptProfile | None = None,
        chat_kind: str | None = None,
    ) -> list[LLMMessage]:
        del system_prompt, prompt_profile, chat_kind
        return [LLMMessage(role="user", content=f"question {chat_id}")]

    async def add_message(
        self,
        *,
        chat_id: int,
        user_id: int | None,
        role: object,
        text: str,
        telegram_message_id: int | None = None,
    ) -> None:
        self.added.append(
            {
                "chat_id": chat_id,
                "user_id": user_id,
                "role": role,
                "text": text,
                "telegram_message_id": telegram_message_id,
            }
        )


class FakeSessionContext:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


class FakeSessionLocal:
    def __call__(self) -> FakeSessionContext:
        return FakeSessionContext()


class FakeRuntimeSettingsService:
    def __init__(self, repository: object) -> None:
        del repository

    async def get_active_llm_provider(self) -> ActiveLLMProvider:
        return ActiveLLMProvider.AUTO

    async def get_prompt_profile(self, scope: PromptProfileScope) -> PromptProfile:
        del scope
        return PromptProfile.BALANCED

    async def get_prompt(self, scope: PromptProfileScope) -> PromptSetting:
        return PromptSetting(scope=scope, text=DEFAULT_PROMPTS[scope], source=PromptSource.DEFAULT)


def patch_worker(
    monkeypatch: pytest.MonkeyPatch,
    *,
    provider: FakeProvider,
    settings: Settings,
) -> None:
    FakeBot.instances = []
    FakeMemoryService.instances = []
    monkeypatch.setattr(jobs, "Bot", FakeBot)
    monkeypatch.setattr(jobs, "get_settings", lambda: settings)
    monkeypatch.setattr(jobs, "SessionLocal", FakeSessionLocal())
    monkeypatch.setattr(jobs, "MessageRepository", lambda session: object())
    monkeypatch.setattr(jobs, "MemoryService", FakeMemoryService)
    monkeypatch.setattr(jobs, "RuntimeSettingRepository", lambda session: object())
    monkeypatch.setattr(jobs, "RuntimeSettingsService", FakeRuntimeSettingsService)
    monkeypatch.setattr(
        jobs,
        "build_llm_provider",
        lambda loaded_settings, *, active_provider: provider,
    )


@pytest.mark.asyncio
async def test_private_streaming_uses_draft_then_final_and_saves_only_final(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = FakeProvider(chunks=["Первый фрагмент. ", "Второй фрагмент."])
    caplog.set_level(logging.INFO)
    patch_worker(
        monkeypatch,
        provider=provider,
        settings=Settings(
            telegram_bot_token="123456:secret-token",
            streaming_enabled=True,
            streaming_private_draft_enabled=True,
            streaming_min_chars_delta=5,
        ),
    )

    await process_llm_message({}, {"chat_id": 100, "user_id": 456, "private": True})

    bot = FakeBot.instances[0]
    memory = FakeMemoryService.instances[0]
    messages = [record.message for record in caplog.records]
    assert provider.stream_called is True
    assert provider.complete_called is False
    assert bot.drafts[0]["draft_id"] != 0
    assert bot.drafts[0]["text"] == ""
    assert bot.sent_messages == [{"chat_id": 100, "text": "Первый фрагмент. Второй фрагмент."}]
    assert [item["text"] for item in memory.added] == ["Первый фрагмент. Второй фрагмент."]
    assert "streaming_private_draft_selected" in messages
    assert "telegram_send_message_draft_called" in messages
    assert "telegram_final_send_message_called" in messages


@pytest.mark.asyncio
async def test_group_streaming_uses_fallback_edit_without_draft_and_private_false(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = FakeProvider(chunks=["DNS нужен. ", "Он помогает находить серверы."])
    caplog.set_level(logging.INFO)
    patch_worker(
        monkeypatch,
        provider=provider,
        settings=Settings(
            telegram_bot_token="123456:secret-token",
            streaming_enabled=True,
            streaming_group_fallback_enabled=True,
            streaming_min_chars_delta=5,
        ),
    )

    await process_llm_message({}, {"chat_id": -100, "user_id": 456, "private": False})

    bot = FakeBot.instances[0]
    memory = FakeMemoryService.instances[0]
    messages = [record.message for record in caplog.records]
    assert provider.stream_called is True
    assert bot.drafts == []
    assert bot.sent_messages[0] == {
        "chat_id": -100,
        "text": "Принял. Готовлю групповой ответ.",
    }
    assert bot.edits[-1] == {
        "chat_id": -100,
        "message_id": 77,
        "text": "DNS нужен. Он помогает находить серверы.",
    }
    assert memory.added[0]["chat_id"] == -100
    assert memory.added[0]["text"] == "DNS нужен. Он помогает находить серверы."
    assert "streaming_group_fallback_selected" in messages
    assert "telegram_group_provisional_sent" in messages
    assert "telegram_group_edit_message_text_called" in messages
    assert "telegram_group_final_edit_called" in messages


@pytest.mark.asyncio
async def test_guest_job_remains_final_only_without_streaming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = FakeProvider(chunks=["stream"], complete_text="guest final")
    patch_worker(
        monkeypatch,
        provider=provider,
        settings=Settings(telegram_bot_token="123456:secret-token", streaming_enabled=True),
    )

    await process_llm_message({}, {"chat_id": 100, "user_id": 456, "private": True, "guest": True})

    bot = FakeBot.instances[0]
    assert provider.stream_called is False
    assert provider.complete_called is True
    assert bot.drafts == []
    assert bot.chat_actions == []
    assert bot.edits == []


@pytest.mark.asyncio
async def test_private_draft_error_falls_back_to_provisional_edit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = FakeProvider(chunks=["Черновик недоступен. ", "Но ответ готов."])
    patch_worker(
        monkeypatch,
        provider=provider,
        settings=Settings(
            telegram_bot_token="123456:secret-token",
            streaming_enabled=True,
            streaming_private_draft_enabled=True,
            streaming_min_chars_delta=5,
        ),
    )
    original_init = FakeBot.__init__

    def init_with_failed_draft(self: FakeBot, token: str) -> None:
        original_init(self, token)
        self.fail_draft = True

    monkeypatch.setattr(FakeBot, "__init__", init_with_failed_draft)

    await process_llm_message({}, {"chat_id": 100, "user_id": 456, "private": True})

    bot = FakeBot.instances[0]
    assert bot.drafts == []
    assert bot.sent_messages[0] == {"chat_id": 100, "text": "Думаю..."}
    assert bot.sent_messages[-1] == {
        "chat_id": 100,
        "text": "Черновик недоступен. Но ответ готов.",
    }


@pytest.mark.asyncio
async def test_stream_provider_error_falls_back_to_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = StreamErrorProvider(complete_text="Обычный финальный ответ")
    patch_worker(
        monkeypatch,
        provider=provider,
        settings=Settings(
            telegram_bot_token="123456:secret-token",
            streaming_enabled=True,
            streaming_private_draft_enabled=True,
        ),
    )

    await process_llm_message({}, {"chat_id": 100, "user_id": 456, "private": True})

    bot = FakeBot.instances[0]
    memory = FakeMemoryService.instances[0]
    assert provider.stream_called is True
    assert provider.complete_called is True
    assert bot.sent_messages == [{"chat_id": 100, "text": "Обычный финальный ответ"}]
    assert [item["text"] for item in memory.added] == ["Обычный финальный ответ"]


@pytest.mark.asyncio
async def test_private_final_response_splits_long_telegram_messages_and_saves_one_full_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    long_text = "я" * (TELEGRAM_TEXT_LIMIT + 100)
    provider = FakeProvider(chunks=[long_text])
    patch_worker(
        monkeypatch,
        provider=provider,
        settings=Settings(
            telegram_bot_token="123456:secret-token",
            streaming_enabled=True,
            streaming_private_draft_enabled=True,
            streaming_min_chars_delta=10,
        ),
    )

    await process_llm_message({}, {"chat_id": 100, "user_id": 456, "private": True})

    bot = FakeBot.instances[0]
    memory = FakeMemoryService.instances[0]
    assert len(bot.sent_messages) == 2
    assert all(len(str(item["text"])) <= TELEGRAM_TEXT_LIMIT for item in bot.sent_messages)
    assert "".join(str(item["text"]) for item in bot.sent_messages) == long_text
    assert [item["text"] for item in memory.added] == [long_text]
