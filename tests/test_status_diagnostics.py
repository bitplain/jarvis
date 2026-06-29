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


@pytest.mark.asyncio
async def test_status_command_shows_helpdesk_vacation_fields_without_ids() -> None:
    message = FakeMessage()

    await cmd_status(
        message,  # type: ignore[arg-type]
        settings=Settings(admin_telegram_ids="100500"),
        status_snapshot={
            "api": {"ok": True},
            "postgres": {"ok": True, "latency_ms": 12},
            "redis": {"ok": True, "latency_ms": 4},
            "worker": {"ok": True, "age_seconds": 8},
            "webhook": {"state": "configured"},
            "reminders": {"ok": True, "due_count": 0},
            "provider": {"label": "Auto"},
            "draft_streaming": {"ok": False},
            "prompt_profiles": {"ok": True},
            "access_db": {"ok": True},
            "helpdesk_imap": {
                "enabled": True,
                "configured": True,
                "host": "configured",
                "port": 993,
                "ssl": True,
                "username": "su***@example.ru",
                "folder": "INBOX",
                "telegram_chat_id": "configured",
                "missing": "none",
                "last_check": "unknown",
                "last_success": "unknown",
                "last_error": "none",
                "baseline": "set",
                "last_seen_uid": 101,
                "mailbox_last_check": "unknown",
                "mailbox_last_success": "unknown",
                "mailbox_last_error": "none",
                "processed_last_24h": 1,
                "pending_notifications": 0,
                "failed_notifications": 0,
                "vacation_enabled": True,
                "vacation_since": "2026-06-29T09:00:00+00:00",
                "vacation_last_reviewed": "unknown",
                "vacation_new_since_start": 2,
                "vacation_new_since_last_review": 2,
            },
        },
    )

    rendered = message.answers[0]["text"]
    assert "- vacation mode: enabled" in rendered
    assert "- vacation since: 2026-06-29T09:00:00+00:00" in rendered
    assert "- vacation new since start: 2" in rendered
    assert "- vacation new since last review: 2" in rendered
    assert "100500" not in rendered
