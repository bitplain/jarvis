from typing import Any

import pytest

from app.bot.routers.commands import cmd_status
from app.core.config import Settings


class FakeMessage:
    def __init__(self, text: str = "/status", *, user_id: int = 100500) -> None:
        self.text = text
        self.caption = None
        self.from_user = type("User", (), {"id": user_id})()
        self.chat = type("Chat", (), {"type": "private"})()
        self.answers: list[dict[str, Any]] = []

    async def answer(self, text: str, **kwargs: Any) -> None:
        self.answers.append({"text": text, **kwargs})


@pytest.mark.asyncio
async def test_status_command_shows_diagnostics_without_ids() -> None:
    message = FakeMessage()

    await cmd_status(
        message,  # type: ignore[arg-type]
        settings=Settings(
            admin_telegram_ids="100500",
        ),
        status_snapshot={
            "api": {"ok": True},
            "postgres": {"ok": True, "latency_ms": 1},
            "redis": {"ok": True, "latency_ms": 1},
            "worker": {"ok": True, "age_seconds": 1},
            "webhook": {"state": "unknown"},
            "reminders": {"ok": True, "due_count": 0},
            "provider": {"label": "Auto"},
            "draft_streaming": {"ok": False},
            "prompt_profiles": {"ok": True},
            "access_db": {"ok": True},
        },
    )

    rendered = message.answers[0]["text"]
    assert "<b>Jarvis status</b>" in rendered
    assert "LLM provider: Auto" in rendered
    assert "100500" not in rendered


@pytest.mark.asyncio
async def test_status_command_for_other_bot_is_ignored() -> None:
    message = FakeMessage("/status@OtherBot")

    await cmd_status(
        message,  # type: ignore[arg-type]
        settings=Settings(admin_telegram_ids="100500", telegram_bot_username="Home_ai_my_bot"),
        status_snapshot={},
    )

    assert message.answers == []
