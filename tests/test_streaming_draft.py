import pytest

from app.bot.streaming.telegram_draft import TelegramDraftNotAvailable, TelegramPrivateDraftSink


class BotWithoutDraft:
    token = "secret-token"


@pytest.mark.asyncio
async def test_private_draft_adapter_falls_back_when_raw_call_fails() -> None:
    async def failing_raw_call(method: str, payload: dict[str, object]) -> dict[str, object]:
        raise RuntimeError("not available")

    sink = TelegramPrivateDraftSink(BotWithoutDraft(), raw_call=failing_raw_call)

    with pytest.raises(TelegramDraftNotAvailable):
        await sink.publish(chat_id=1, text="draft")
