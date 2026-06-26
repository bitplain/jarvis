import pytest
from aiogram.exceptions import TelegramBadRequest

from app.bot.streaming.telegram_fallback import TelegramGroupEditSink
from app.bot.streaming.text_limits import TELEGRAM_TEXT_LIMIT


class FakeMessage:
    def __init__(self, message_id: int) -> None:
        self.message_id = message_id


class FakeBot:
    def __init__(
        self,
        *,
        fail_final_edit: bool = False,
        not_modified_final_edit: bool = False,
    ) -> None:
        self.fail_final_edit = fail_final_edit
        self.not_modified_final_edit = not_modified_final_edit
        self.chat_actions: list[dict[str, object]] = []
        self.sent_messages: list[dict[str, object]] = []
        self.edits: list[dict[str, object]] = []

    async def send_chat_action(self, **kwargs: object) -> None:
        self.chat_actions.append(kwargs)

    async def send_message(self, **kwargs: object) -> FakeMessage:
        self.sent_messages.append(kwargs)
        return FakeMessage(55)

    async def edit_message_text(self, **kwargs: object) -> None:
        if self.not_modified_final_edit and str(kwargs.get("text", "")).startswith(
            "Финальный ответ"
        ):
            raise TelegramBadRequest(
                method=None,  # type: ignore[arg-type]
                message="Bad Request: message is not modified",
            )
        if self.fail_final_edit:
            raise TelegramBadRequest(
                method=None,  # type: ignore[arg-type]
                message="Bad Request: message to edit not found",
            )
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
    assert bot.sent_messages == [{"chat_id": -100, "text": "Думаю"}]
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
        {"chat_id": -100, "text": "Думаю"},
        {"chat_id": -100, "text": "Финальный ответ"},
    ]


@pytest.mark.asyncio
async def test_group_final_edit_success_sends_no_duplicate() -> None:
    bot = FakeBot()
    sink = TelegramGroupEditSink(bot, edit_interval_ms=1000, chat_action_interval_seconds=4)

    await sink.start(chat_id=-100)
    await sink.final(chat_id=-100, text="Финальный ответ")
    await sink.final(chat_id=-100, text="Финальный ответ")

    assert bot.sent_messages == [{"chat_id": -100, "text": "Думаю"}]
    assert bot.edits[-1] == {"chat_id": -100, "message_id": 55, "text": "Финальный ответ"}
    assert len(bot.edits) == 1


@pytest.mark.asyncio
async def test_group_final_edit_failure_sends_one_fallback() -> None:
    bot = FakeBot(fail_final_edit=True)
    sink = TelegramGroupEditSink(bot, edit_interval_ms=1000, chat_action_interval_seconds=4)

    await sink.start(chat_id=-100)
    await sink.final(chat_id=-100, text="Финальный ответ")
    await sink.final(chat_id=-100, text="Финальный ответ")

    assert bot.sent_messages == [
        {"chat_id": -100, "text": "Думаю"},
        {"chat_id": -100, "text": "Финальный ответ"},
    ]


@pytest.mark.asyncio
async def test_group_message_not_modified_is_success() -> None:
    bot = FakeBot(not_modified_final_edit=True)
    sink = TelegramGroupEditSink(bot, edit_interval_ms=1000, chat_action_interval_seconds=4)

    await sink.start(chat_id=-100)
    await sink.final(chat_id=-100, text="Финальный ответ")

    assert bot.sent_messages == [{"chat_id": -100, "text": "Думаю"}]


@pytest.mark.asyncio
async def test_group_long_message_not_modified_sends_remaining_chunks_once() -> None:
    long_text = "Финальный ответ" + ("я" * TELEGRAM_TEXT_LIMIT)
    bot = FakeBot(not_modified_final_edit=True)
    sink = TelegramGroupEditSink(bot, edit_interval_ms=1000, chat_action_interval_seconds=4)

    await sink.start(chat_id=-100)
    await sink.final(chat_id=-100, text=long_text)
    await sink.final(chat_id=-100, text=long_text)

    final_messages = bot.sent_messages[1:]
    assert len(final_messages) == 1
    assert final_messages[0]["text"] == long_text[TELEGRAM_TEXT_LIMIT:]


@pytest.mark.asyncio
async def test_group_long_final_split_once() -> None:
    long_text = "я" * (TELEGRAM_TEXT_LIMIT + 100)
    bot = FakeBot(fail_final_edit=True)
    sink = TelegramGroupEditSink(bot, edit_interval_ms=1000, chat_action_interval_seconds=4)

    await sink.start(chat_id=-100)
    await sink.final(chat_id=-100, text=long_text)
    await sink.final(chat_id=-100, text=long_text)

    final_messages = bot.sent_messages[1:]
    assert len(final_messages) == 2
    assert all(len(str(item["text"])) <= TELEGRAM_TEXT_LIMIT for item in final_messages)
    assert "".join(str(item["text"]) for item in final_messages) == long_text


@pytest.mark.asyncio
async def test_group_edit_sink_truncates_preview_edits_to_telegram_limit() -> None:
    bot = FakeBot()
    sink = TelegramGroupEditSink(bot, edit_interval_ms=1000, chat_action_interval_seconds=4)

    await sink.start(chat_id=-100)
    await sink.publish(chat_id=-100, text="я" * (TELEGRAM_TEXT_LIMIT + 100), now=1.0)

    assert len(str(bot.edits[-1]["text"])) <= TELEGRAM_TEXT_LIMIT
