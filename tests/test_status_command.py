from typing import Any

import pytest

from app.bot.routers.commands import cmd_status
from app.core.config import Settings


class FakeMessage:
    def __init__(self, text: str = "/status") -> None:
        self.text = text
        self.caption = None
        self.answers: list[str] = []

    async def answer(self, text: str, **kwargs: Any) -> None:
        self.answers.append(text)


@pytest.mark.asyncio
async def test_status_command_shows_business_flags_and_counts_without_ids() -> None:
    message = FakeMessage()

    await cmd_status(
        message,  # type: ignore[arg-type]
        settings=Settings(
            admin_telegram_ids="100500",
            guest_mode_enabled=True,
            business_mode_enabled=True,
            business_reply_enabled=False,
            business_admin_only=True,
        ),
        business_status_counts=(3, 1),
    )

    rendered = message.answers[0]
    assert "Business Mode: enabled" in rendered
    assert "Business Reply: disabled" in rendered
    assert "Business Admin Only: true" in rendered
    assert "Business Connections: 3" in rendered
    assert "Business Active Connections: 1" in rendered
    assert "100500" not in rendered


@pytest.mark.asyncio
async def test_status_command_for_other_bot_is_ignored() -> None:
    message = FakeMessage("/status@OtherBot")

    await cmd_status(
        message,  # type: ignore[arg-type]
        settings=Settings(telegram_bot_username="Home_ai_my_bot"),
        business_status_counts=(0, 0),
    )

    assert message.answers == []
