from typing import Any

import pytest

from app.bot.routers.commands import cmd_status
from app.core.config import Settings


class FakeMessage:
    def __init__(self) -> None:
        self.text = "/status"
        self.caption = None
        self.from_user = type("User", (), {"id": 100500})()
        self.chat = type("Chat", (), {"type": "private"})()
        self.answers: list[dict[str, Any]] = []

    async def answer(self, text: str, **kwargs: Any) -> None:
        self.answers.append({"text": text, **kwargs})


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
        status_snapshot={
            "api": {"ok": True},
            "postgres": {"ok": True, "latency_ms": 1},
            "redis": {"ok": True, "latency_ms": 1},
            "worker": {"ok": True, "age_seconds": 1},
            "webhook": {"state": "configured"},
            "reminders": {"ok": True, "due_count": 0},
            "provider": {"label": "Auto"},
            "draft_streaming": {"ok": True},
            "prompt_profiles": {"ok": True},
            "access_db": {"ok": True},
        },
    )

    rendered = message.answers[0]["text"]
    assert "Draft streaming: ✅ enabled" in rendered
    assert "Webhook: ✅ configured" in rendered
    assert "100500" not in rendered
