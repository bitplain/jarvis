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
async def test_status_shows_core_diagnostics_by_default() -> None:
    message = FakeMessage()

    await cmd_status(
        message,  # type: ignore[arg-type]
        settings=Settings(admin_telegram_ids="100500"),
        status_snapshot={
            "api": {"ok": True},
            "postgres": {"ok": True, "latency_ms": 10},
            "redis": {"ok": False, "latency_ms": None},
            "worker": {"ok": False, "age_seconds": None},
            "webhook": {"state": "unknown"},
            "reminders": {"ok": False, "due_count": None},
            "provider": {"label": "Auto"},
            "draft_streaming": {"ok": False},
            "prompt_profiles": {"ok": False},
            "access_db": {"ok": False},
        },
    )

    rendered = message.answers[0]["text"]
    assert "API: ✅ ok" in rendered
    assert "Redis: ⚠️ degraded" in rendered
    assert "Webhook: ⚠️ unknown" in rendered
    assert "100500" not in rendered


@pytest.mark.asyncio
async def test_status_shows_provider_label() -> None:
    message = FakeMessage()

    await cmd_status(
        message,  # type: ignore[arg-type]
        settings=Settings(admin_telegram_ids="100500"),
        status_snapshot={
            "api": {"ok": True},
            "postgres": {"ok": True, "latency_ms": 10},
            "redis": {"ok": True, "latency_ms": 4},
            "worker": {"ok": True, "age_seconds": 1},
            "webhook": {"state": "configured"},
            "reminders": {"ok": True, "due_count": 2},
            "provider": {"label": "OpenRouter"},
            "draft_streaming": {"ok": True},
            "prompt_profiles": {"ok": True},
            "access_db": {"ok": True},
        },
    )

    rendered = message.answers[0]["text"]
    assert "LLM provider: OpenRouter" in rendered
    assert "Draft streaming: ✅ enabled" in rendered
