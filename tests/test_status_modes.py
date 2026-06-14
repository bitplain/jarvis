from typing import Any

import pytest

from app.bot.routers.commands import cmd_status
from app.core.config import Settings


class FakeMessage:
    def __init__(self) -> None:
        self.answers: list[str] = []

    async def answer(self, text: str, **kwargs: Any) -> None:
        self.answers.append(text)


@pytest.mark.asyncio
async def test_status_shows_regular_modes_and_business_optional_by_default() -> None:
    message = FakeMessage()

    await cmd_status(
        message,  # type: ignore[arg-type]
        settings=Settings(admin_telegram_ids="100500", guest_mode_enabled=False),
        business_status_counts=(0, 0),
    )

    rendered = message.answers[0]
    assert "Personal Chat: enabled" in rendered
    assert "Group Assistant: enabled" in rendered
    assert "Guest Mode: disabled" in rendered
    assert "Forwarded Assistant: enabled" in rendered
    assert "Draft Reply: enabled" in rendered
    assert "Business Mode: optional/disabled" in rendered
    assert "Business Reply: disabled" in rendered
    assert "100500" not in rendered


@pytest.mark.asyncio
async def test_status_shows_business_enabled_only_when_explicitly_enabled() -> None:
    message = FakeMessage()

    await cmd_status(
        message,  # type: ignore[arg-type]
        settings=Settings(
            business_mode_enabled=True,
            business_reply_enabled=True,
            business_admin_only=True,
        ),
        business_status_counts=(1, 1),
    )

    rendered = message.answers[0]
    assert "Business Mode: enabled" in rendered
    assert "Business Reply: enabled" in rendered
