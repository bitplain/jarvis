from typing import Any

import pytest

from app.bot.routers.commands import cmd_helpdesk_baseline_now, cmd_status
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


@pytest.mark.asyncio
async def test_helpdesk_baseline_now_admin_command_sets_baseline_without_notifications() -> None:
    class FakeBaselineService:
        async def baseline_now(self) -> object:
            return type("BaselineResult", (), {"status": "baseline_set", "last_seen_uid": 12345})()

    message = FakeMessage("/helpdesk_baseline_now")

    await cmd_helpdesk_baseline_now(
        message,  # type: ignore[arg-type]
        settings=Settings(
            admin_telegram_ids="100500",
            helpdesk_imap_enabled=True,
            helpdesk_imap_host="imap.example.ru",
            helpdesk_imap_username="support@example.ru",
            helpdesk_imap_password="real-password",
            helpdesk_telegram_chat_id="-1001234567890",
        ),
        helpdesk_baseline_service=FakeBaselineService(),
    )

    assert message.answers == [
        {
            "text": (
                "HelpDesk baseline обновлён.\n"
                "Старые письма до UID 12345 больше не будут отправляться."
            )
        }
    ]


@pytest.mark.asyncio
async def test_helpdesk_baseline_now_reports_not_configured_without_imap_call() -> None:
    class UnexpectedBaselineService:
        async def baseline_now(self) -> object:
            raise AssertionError("baseline service must not be called")

    message = FakeMessage("/helpdesk_baseline_now")

    await cmd_helpdesk_baseline_now(
        message,  # type: ignore[arg-type]
        settings=Settings(admin_telegram_ids="100500", helpdesk_imap_enabled=False),
        helpdesk_baseline_service=UnexpectedBaselineService(),
    )

    assert message.answers == [{"text": "HelpDesk IMAP не настроен."}]
