from typing import Any

import pytest

from app.core.config import Settings
from app.services.status_service import StatusService, render_status_html
from app.workers import jobs
from app.workers.arq_settings import WorkerSettings


def test_helpdesk_worker_is_registered() -> None:
    assert jobs.check_helpdesk_imap_mailbox in WorkerSettings.functions
    assert any(
        getattr(cron_job, "coroutine", None) is jobs.check_helpdesk_imap_mailbox
        or getattr(cron_job, "name", "") == "cron:check_helpdesk_imap_mailbox"
        for cron_job in WorkerSettings.cron_jobs
    )


class FakeRedis:
    async def get(self, key: str) -> bytes | None:
        values = {
            "jarvis:helpdesk_imap:last_check": b"2026-06-27T10:00:00+00:00",
            "jarvis:helpdesk_imap:last_success": b"2026-06-27T10:00:02+00:00",
            "jarvis:helpdesk_imap:last_error": b"none",
        }
        return values.get(key)


class FakeCountResult:
    def __init__(self, value: int) -> None:
        self.value = value

    def scalar_one(self) -> int:
        return self.value

    def scalar_one_or_none(self) -> None:
        return None


class FakeStatusSession:
    async def execute(self, statement: Any) -> FakeCountResult:
        rendered = str(statement)
        if "helpdesk_email_events" in rendered and "notify_status" in rendered:
            return FakeCountResult(1)
        if "helpdesk_email_events" in rendered:
            return FakeCountResult(3)
        return FakeCountResult(0)

    async def rollback(self) -> None:
        return None


@pytest.mark.asyncio
async def test_status_collects_helpdesk_imap_without_live_imap_connection() -> None:
    service = StatusService(
        Settings(
            helpdesk_imap_enabled=True,
            helpdesk_imap_host="imap.example.ru",
            helpdesk_imap_username="support@example.ru",
            helpdesk_imap_password="real-password",
            helpdesk_telegram_chat_id="-1001234567890",
        ),
        session=FakeStatusSession(),  # type: ignore[arg-type]
        redis=FakeRedis(),
    )

    snapshot = await service.collect()

    assert snapshot["helpdesk_imap"]["enabled"] is True
    assert snapshot["helpdesk_imap"]["configured"] is True
    assert snapshot["helpdesk_imap"]["host"] == "configured"
    assert snapshot["helpdesk_imap"]["port"] == 993
    assert snapshot["helpdesk_imap"]["ssl"] is True
    assert snapshot["helpdesk_imap"]["username"] == "s***t@example.ru"
    assert snapshot["helpdesk_imap"]["telegram_chat_id"] == "configured"
    assert snapshot["helpdesk_imap"]["missing"] == "none"
    assert snapshot["helpdesk_imap"]["processed_last_24h"] == 3
    assert snapshot["helpdesk_imap"]["pending_notifications"] == 1
    assert "real-password" not in str(snapshot)
    assert "support@example.ru" not in str(snapshot)


def test_status_render_includes_helpdesk_imap_section_without_password() -> None:
    rendered = render_status_html(
        {
            "api": {"ok": True},
            "postgres": {"ok": True, "latency_ms": 1},
            "redis": {"ok": True, "latency_ms": 1},
            "worker": {"ok": True, "age_seconds": 1},
            "webhook": {"state": "configured"},
            "reminders": {"ok": True, "due_count": 0},
            "provider": {"label": "Auto"},
            "draft_streaming": {"ok": False},
            "prompt_profiles": {"ok": True},
            "access_db": {"ok": True},
            "helpdesk_imap": {
                "enabled": True,
                "configured": False,
                "host": "missing",
                "port": 993,
                "ssl": True,
                "username": "missing",
                "folder": "INBOX",
                "telegram_chat_id": "missing",
                "missing": "helpdesk_imap_host, helpdesk_telegram_chat_id",
                "last_check": "unknown",
                "last_success": "unknown",
                "last_error": "config",
                "processed_last_24h": 0,
                "pending_notifications": 0,
            },
        }
    )

    assert "HelpDesk IMAP:" in rendered
    assert "- enabled: yes" in rendered
    assert "- configured: no" in rendered
    assert "- port: 993" in rendered
    assert "- ssl: yes" in rendered
    assert "- telegram chat id: missing" in rendered
    assert "- missing: helpdesk_imap_host, helpdesk_telegram_chat_id" in rendered
    assert "- last error: config" in rendered
    assert "password" not in rendered.lower()


@pytest.mark.asyncio
async def test_helpdesk_cron_disabled_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    class FakeService:
        def __init__(self, *args: object, **kwargs: object) -> None:
            nonlocal called
            called = True

        async def run_once(self) -> object:
            return object()

    monkeypatch.setattr(jobs, "get_settings", lambda: Settings(helpdesk_imap_enabled=False))
    monkeypatch.setattr(jobs, "HelpdeskImapService", FakeService)

    await jobs.check_helpdesk_imap_mailbox({})

    assert called is False
