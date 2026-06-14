from typing import Any

import pytest

from app.bot.middlewares.group_diagnostics import GroupDiagnosticsMiddleware
from app.core.config import Settings


class FakeChat:
    type = "supergroup"
    id = -100123456


class FakeUser:
    id = 100500


class FakeBotUser:
    id = 999
    username = "jarvis_bot"


class FakeBot:
    async def get_me(self) -> FakeBotUser:
        return FakeBotUser()


class FakeMessage:
    def __init__(self, text: str) -> None:
        self.chat = FakeChat()
        self.from_user = FakeUser()
        self.text = text
        self.message_id = 77
        self.reply_to_message = None


@pytest.mark.asyncio
async def test_group_diagnostics_logs_command_mention_without_message_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def fake_info(message: str, **kwargs: Any) -> None:
        calls.append({"message": message, **kwargs})

    monkeypatch.setattr("app.bot.middlewares.group_diagnostics.logger.info", fake_info)
    middleware = GroupDiagnosticsMiddleware(Settings(telegram_bot_username="jarvis_bot"))

    async def handler(event: object, data: dict[str, Any]) -> str:
        del event, data
        return "handled"

    result = await middleware(
        handler,
        FakeMessage("/status@jarvis_bot"),  # type: ignore[arg-type]
        {"bot": FakeBot()},
    )

    assert result == "handled"
    logged = calls[0]["extra"]
    assert calls[0]["message"] == "group_message_update"
    assert logged["update_type"] == "message"
    assert logged["chat_type"] == "supergroup"
    assert logged["chat_id_masked"] == "-***3456"
    assert logged["from_user_masked"] == "***0500"
    assert logged["text_classification"] == "command_mention"
    assert logged["matched_bot_username"] is True
    assert logged["should_process"] is True
    assert "/status" not in str(logged)
