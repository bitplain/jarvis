import pytest

from app.bot.streaming.telegram_draft import TelegramDraftNotAvailable, TelegramPrivateDraftSink
from app.bot.streaming.text_limits import TELEGRAM_TEXT_LIMIT


class FakeDraftBot:
    token = "123456:secret-token"

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.fail_rich_draft = False

    async def send_rich_message_draft(self, **kwargs: object) -> None:
        if self.fail_rich_draft:
            raise RuntimeError("rich draft unavailable")
        self.calls.append({"method": "send_rich_message_draft", **kwargs})

    async def send_message_draft(self, **kwargs: object) -> None:
        self.calls.append(kwargs)

    async def send_message(self, **kwargs: object) -> None:
        self.calls.append({"method": "send_message", **kwargs})


class FakeDraftBotRejectingEmpty(FakeDraftBot):
    async def send_message_draft(self, **kwargs: object) -> None:
        if kwargs.get("text") == "":
            raise RuntimeError("empty draft rejected")
        await super().send_message_draft(**kwargs)


class BotWithoutDraft:
    token = "123456:secret-token"


@pytest.mark.asyncio
async def test_private_draft_uses_non_zero_draft_id_and_placeholder() -> None:
    bot = FakeDraftBot()
    sink = TelegramPrivateDraftSink(bot, draft_id=42)

    await sink.start(chat_id=100)
    await sink.publish(chat_id=100, text="Черновик")

    assert bot.calls == [
        {"chat_id": 100, "draft_id": 42, "text": ""},
        {"chat_id": 100, "draft_id": 42, "text": "Черновик"},
    ]


@pytest.mark.asyncio
async def test_private_mira_draft_starts_with_rich_thinking_block() -> None:
    bot = FakeDraftBot()
    sink = TelegramPrivateDraftSink(bot, draft_id=42, rich_thinking_enabled=True)

    await sink.start(chat_id=100)
    await sink.publish(chat_id=100, text="Ответ растёт")

    assert bot.calls == [
        {
            "method": "send_rich_message_draft",
            "chat_id": 100,
            "draft_id": 42,
            "rich_message": {"html": "<tg-thinking>Думаю</tg-thinking>"},
        },
        {"chat_id": 100, "draft_id": 42, "text": "Ответ растёт"},
    ]


@pytest.mark.asyncio
async def test_private_mira_draft_falls_back_to_text_thinking_when_rich_fails() -> None:
    bot = FakeDraftBot()
    bot.fail_rich_draft = True
    sink = TelegramPrivateDraftSink(bot, draft_id=42, rich_thinking_enabled=True)

    await sink.start(chat_id=100)
    await sink.publish(chat_id=100, text="Ответ")

    assert sink.available is True
    assert bot.calls == [
        {"chat_id": 100, "draft_id": 42, "text": "Думаю"},
        {"chat_id": 100, "draft_id": 42, "text": "Ответ"},
    ]


@pytest.mark.asyncio
async def test_private_draft_keeps_job_available_when_empty_placeholder_fails() -> None:
    bot = FakeDraftBotRejectingEmpty()
    sink = TelegramPrivateDraftSink(bot, draft_id=42)

    await sink.start(chat_id=100)
    await sink.publish(chat_id=100, text="Черновик")

    assert sink.available is True
    assert bot.calls == [{"chat_id": 100, "draft_id": 42, "text": "Черновик"}]


@pytest.mark.asyncio
async def test_private_draft_raw_adapter_isolated_and_masks_failures() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    async def raw_call(method: str, payload: dict[str, object]) -> dict[str, object]:
        calls.append((method, payload))
        return {"ok": True}

    sink = TelegramPrivateDraftSink(BotWithoutDraft(), draft_id=7, raw_call=raw_call)

    await sink.publish(chat_id=100, text="Черновик", message_thread_id=5)

    assert calls == [
        (
            "sendMessageDraft",
            {"chat_id": 100, "draft_id": 7, "text": "Черновик", "message_thread_id": 5},
        )
    ]


@pytest.mark.asyncio
async def test_private_mira_draft_raw_adapter_sends_rich_thinking_block() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    async def raw_call(method: str, payload: dict[str, object]) -> dict[str, object]:
        calls.append((method, payload))
        return {"ok": True}

    sink = TelegramPrivateDraftSink(
        BotWithoutDraft(),
        draft_id=7,
        raw_call=raw_call,
        rich_thinking_enabled=True,
    )

    await sink.start(chat_id=100, message_thread_id=5)

    assert calls == [
        (
            "sendRichMessageDraft",
            {
                "chat_id": 100,
                "draft_id": 7,
                "rich_message": {"html": "<tg-thinking>Думаю</tg-thinking>"},
                "message_thread_id": 5,
            },
        )
    ]


@pytest.mark.asyncio
async def test_private_draft_adapter_falls_back_when_raw_call_fails() -> None:
    async def failing_raw_call(method: str, payload: dict[str, object]) -> dict[str, object]:
        raise RuntimeError("not available")

    sink = TelegramPrivateDraftSink(BotWithoutDraft(), draft_id=1, raw_call=failing_raw_call)

    with pytest.raises(TelegramDraftNotAvailable):
        await sink.publish(chat_id=1, text="draft")


@pytest.mark.asyncio
async def test_private_draft_final_send_message_happens_after_draft() -> None:
    bot = FakeDraftBot()
    sink = TelegramPrivateDraftSink(bot, draft_id=9)

    await sink.publish(chat_id=100, text="Черновик")
    await sink.final(chat_id=100, text="Финальный ответ")

    assert bot.calls[-1] == {"method": "send_message", "chat_id": 100, "text": "Финальный ответ"}


@pytest.mark.asyncio
async def test_private_draft_truncates_preview_to_telegram_limit() -> None:
    bot = FakeDraftBot()
    sink = TelegramPrivateDraftSink(bot, draft_id=9)

    await sink.publish(chat_id=100, text="я" * (TELEGRAM_TEXT_LIMIT + 100))

    assert len(str(bot.calls[-1]["text"])) <= TELEGRAM_TEXT_LIMIT
