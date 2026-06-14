import pytest

from app.bot.streaming.telegram_fallback import TelegramGroupEditSink
from app.bot.streaming.text_limits import TELEGRAM_TEXT_LIMIT


class FakeMessage:
    def __init__(self, message_id: int) -> None:
        self.message_id = message_id


class FakeBot:
    def __init__(self, *, fail_final_edit: bool = False) -> None:
        self.fail_final_edit = fail_final_edit
        self.chat_actions: list[dict[str, object]] = []
        self.sent_messages: list[dict[str, object]] = []
        self.edits: list[dict[str, object]] = []

    async def send_chat_action(self, **kwargs: object) -> None:
        self.chat_actions.append(kwargs)

    async def send_message(self, **kwargs: object) -> FakeMessage:
        self.sent_messages.append(kwargs)
        return FakeMessage(55)

    async def edit_message_text(self, **kwargs: object) -> None:
        if self.fail_final_edit and kwargs.get("text") == "Финальный ответ":
            raise RuntimeError("edit failed")
        self.edits.append(kwargs)


@pytest.mark.asyncio
async def test_group_edit_sink_sends_typing_provisional_and_throttled_edits() -> None:
    bot = FakeBot()
    sink = TelegramGroupEditSink(bot, edit_interval_ms=1000, chat_action_interval_seconds=4)

    await sink.start(chat_id=-100)
    await sink.publish(chat_id=-100, text="раз", now=0.0)
    await sink.publish(chat_id=-100, text="раз два", now=0.5)
    await sink.publish(chat_id=-100, text="раз два три", now=1.0)

    assert bot.chat_actions == [{"chat_id": -100, "action": "typing"}]
    assert bot.sent_messages == [{"chat_id": -100, "text": "Думаю..."}]
    assert bot.edits == [
        {"chat_id": -100, "message_id": 55, "text": "раз"},
        {"chat_id": -100, "message_id": 55, "text": "раз два три"},
    ]


@pytest.mark.asyncio
async def test_group_edit_sink_repeats_typing_action() -> None:
    bot = FakeBot()
    sink = TelegramGroupEditSink(bot, edit_interval_ms=1000, chat_action_interval_seconds=4)

    await sink.start(chat_id=-100, now=0.0)
    await sink.publish(chat_id=-100, text="текст", now=4.0)

    assert bot.chat_actions == [
        {"chat_id": -100, "action": "typing"},
        {"chat_id": -100, "action": "typing"},
    ]


@pytest.mark.asyncio
async def test_group_edit_sink_final_sends_message_when_final_edit_fails() -> None:
    bot = FakeBot(fail_final_edit=True)
    sink = TelegramGroupEditSink(bot, edit_interval_ms=1000, chat_action_interval_seconds=4)

    await sink.start(chat_id=-100)
    await sink.final(chat_id=-100, text="Финальный ответ")

    assert bot.sent_messages == [
        {"chat_id": -100, "text": "Думаю..."},
        {"chat_id": -100, "text": "Финальный ответ"},
    ]


@pytest.mark.asyncio
async def test_group_edit_sink_truncates_preview_edits_to_telegram_limit() -> None:
    bot = FakeBot()
    sink = TelegramGroupEditSink(bot, edit_interval_ms=1000, chat_action_interval_seconds=4)

    await sink.start(chat_id=-100)
    await sink.publish(chat_id=-100, text="я" * (TELEGRAM_TEXT_LIMIT + 100), now=1.0)

    assert len(str(bot.edits[-1]["text"])) <= TELEGRAM_TEXT_LIMIT
