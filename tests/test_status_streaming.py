from typing import Any

import pytest

from app.bot.routers.commands import cmd_status
from app.core.config import Settings


class FakeMessage:
    def __init__(self) -> None:
        self.text = "/status"
        self.caption = None
        self.answers: list[str] = []

    async def answer(self, text: str, **kwargs: Any) -> None:
        self.answers.append(text)


@pytest.mark.asyncio
async def test_status_shows_streaming_flags_without_secrets() -> None:
    message = FakeMessage()

    await cmd_status(
        message,  # type: ignore[arg-type]
        settings=Settings(
            admin_telegram_ids="100500",
            streaming_enabled=True,
            streaming_private_draft_enabled=True,
            streaming_group_fallback_enabled=True,
            streaming_draft_raw_api_fallback=True,
        ),
        business_status_counts=(0, 0),
    )

    rendered = message.answers[0]
    assert "Streaming: enabled" in rendered
    assert "Private Draft Streaming: enabled" in rendered
    assert "Group Fallback Streaming: enabled" in rendered
    assert "Draft Raw API Fallback: enabled" in rendered
    assert "100500" not in rendered
