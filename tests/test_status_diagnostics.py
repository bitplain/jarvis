from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.bot.routers.commands import cmd_status
from app.core.config import Settings


class FakeMessage:
    def __init__(
        self,
        text: str = "/status",
        *,
        user_id: int | None = 100500,
        chat_type: str = "private",
    ) -> None:
        self.text = text
        self.caption = None
        self.answers: list[dict[str, Any]] = []
        self.from_user = type("User", (), {"id": user_id})() if user_id is not None else None
        self.chat = type("Chat", (), {"id": user_id or 1, "type": chat_type})()

    async def answer(self, text: str, **kwargs: Any) -> None:
        self.answers.append({"text": text, **kwargs})


@pytest.mark.asyncio
async def test_status_command_admin_renders_html_diagnostics_without_secrets() -> None:
    message = FakeMessage()

    await cmd_status(
        message,  # type: ignore[arg-type]
        settings=Settings(
            admin_telegram_ids="100500",
            telegram_bot_token="123456:secret-token",
            telegram_webhook_secret="secret",
            yandex_ai_api_key="ya-secret",
            openrouter_api_key="or-secret",
            streaming_enabled=True,
            streaming_private_draft_enabled=True,
            telegram_private_draft_streaming_enabled=True,
        ),
        status_snapshot={
            "api": {"ok": True},
            "postgres": {"ok": True, "latency_ms": 12},
            "redis": {"ok": True, "latency_ms": 4},
            "worker": {"ok": True, "age_seconds": 8},
            "webhook": {"state": "configured"},
            "reminders": {"ok": True, "due_count": 0},
            "provider": {"label": "Auto"},
            "draft_streaming": {"ok": True},
            "prompt_profiles": {"ok": True},
            "access_db": {"ok": True},
        },
    )

    answer = message.answers[0]
    rendered = answer["text"]
    assert answer["parse_mode"] == "HTML"
    assert "<b>Jarvis status</b>" in rendered
    assert "PostgreSQL: ✅ ok" in rendered
    assert "Redis: ✅ ok" in rendered
    assert "Worker: ✅ ok" in rendered
    assert "Webhook: ✅ configured" in rendered
    assert "LLM provider: Auto" in rendered
    assert "Draft streaming: ✅ enabled" in rendered
    assert "DB latency: 12 ms" in rendered
    assert "Redis latency: 4 ms" in rendered
    assert "Due reminders: 0" in rendered
    assert "secret-token" not in rendered
    assert "ya-secret" not in rendered
    assert "or-secret" not in rendered
    assert "100500" not in rendered


@pytest.mark.asyncio
async def test_status_command_non_admin_private_is_denied() -> None:
    message = FakeMessage(user_id=200600)

    await cmd_status(
        message,  # type: ignore[arg-type]
        settings=Settings(admin_telegram_ids="100500"),
        status_snapshot={},
    )

    assert message.answers == [{"text": "Доступ запрещён."}]


@pytest.mark.asyncio
async def test_status_command_non_admin_group_is_silent() -> None:
    message = FakeMessage(user_id=200600, chat_type="group")

    await cmd_status(
        message,  # type: ignore[arg-type]
        settings=Settings(admin_telegram_ids="100500"),
        status_snapshot={},
    )

    assert message.answers == []


def test_status_worker_freshness_boundary() -> None:
    from app.services.status_service import is_worker_heartbeat_fresh

    now = datetime(2026, 6, 26, 12, 0, tzinfo=UTC)
    assert is_worker_heartbeat_fresh(now - timedelta(seconds=119), now=now)
    assert not is_worker_heartbeat_fresh(now - timedelta(minutes=6), now=now)
