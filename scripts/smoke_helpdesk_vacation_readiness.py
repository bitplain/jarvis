from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.services.helpdesk_vacation import (
    HelpdeskVacationService,
    InMemoryHelpdeskVacationRepository,
    format_helpdesk_vacation_review_html,
)

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class HelpdeskVacationReadinessResult:
    statuses: dict[str, str] = field(default_factory=dict)
    verdict: str = "PARTIAL_HELPDESK_VACATION_READINESS_NEEDS_FIX"

    def render_sanitized(self) -> str:
        lines = ["Stage 4L-3 HelpDesk vacation readiness sanitized result:"]
        for key in sorted(self.statuses):
            lines.append(f"{key}: {self.statuses[key]}")
        lines.append(f"verdict: {self.verdict}")
        return "\n".join(lines)


def _read(path: str) -> str:
    target = ROOT / path
    if not target.exists():
        return ""
    return target.read_text(encoding="utf-8")


async def run_readiness() -> HelpdeskVacationReadinessResult:
    result = HelpdeskVacationReadinessResult()
    models = _read("app/db/models.py")
    migration = _read("alembic/versions/20260629_0015_helpdesk_vacation_state.py")
    vacation_service = _read("app/services/helpdesk_vacation.py")
    vacation_repo = _read("app/db/repositories/helpdesk_vacation.py")
    imap_service = _read("app/services/helpdesk_imap/service.py")
    event_repo = _read("app/db/repositories/helpdesk_email_events.py")
    ticket_repo = _read("app/db/repositories/helpdesk_ticket_work_items.py")
    workflow = _read("app/services/helpdesk_ticket_workflow.py")
    router = _read("app/bot/routers/helpdesk_tickets.py")
    settings_router = _read("app/bot/routers/commands.py")
    worker = _read("app/workers/jobs.py")
    status = _read("app/services/status_service.py")
    docs = "\n".join(
        [
            _read("AGENTS.md"),
            _read("README.md"),
            _read("docs/ARCHITECTURE.md"),
            _read("docs/STAGE_4L3_HELPDESK_VACATION_MODE_REPORT.md"),
        ]
    )
    tests = "\n".join(
        [
            _read("tests/test_helpdesk_vacation_service.py"),
            _read("tests/test_helpdesk_imap_service.py"),
            _read("tests/test_helpdesk_ticket_workflow_service.py"),
            _read("tests/test_worker_jobs.py"),
            _read("tests/test_helpdesk_ticket_workflow_router.py"),
            _read("tests/test_status_diagnostics.py"),
            _read("tests/test_smoke_helpdesk_vacation_readiness.py"),
        ]
    )

    result.statuses["model_migration"] = (
        "OK"
        if all(
            token in models + migration
            for token in [
                "helpdesk_vacation_state",
                "enabled_at",
                "disabled_at",
                "last_reviewed_at",
                "enabled_by_user_id",
                "disabled_by_user_id",
                "uq_helpdesk_vacation_state_scope",
                "20260629_0015",
            ]
        )
        else "MISSING"
    )
    result.statuses["service_repository"] = (
        "OK"
        if all(
            token in vacation_service + vacation_repo
            for token in [
                "HelpdeskVacationService",
                "is_enabled",
                "enable",
                "disable",
                "summary",
                "review_items",
                "mark_reviewed",
                "suppressed_vacation",
                "format_helpdesk_vacation_review_html",
            ]
        )
        else "MISSING"
    )
    result.statuses["imap_suppression"] = (
        "OK"
        if all(
            token in imap_service + event_repo
            for token in [
                "vacation_service",
                "mark_suppressed_vacation",
                "helpdesk_notification_suppressed_vacation",
                "suppressed_vacation",
            ]
        )
        and "mark_notify_failed(event_id, error_code=\"vacation\")" not in imap_service
        else "MISSING"
    )
    result.statuses["reminder_suppression"] = (
        "OK"
        if all(
            token in worker + ticket_repo + workflow
            for token in [
                "_helpdesk_vacation_enabled",
                "reschedule_active_reminders_after",
                "reschedule_active_reminders_after_vacation",
                "helpdesk_ticket_reminders_suppressed_vacation",
            ]
        )
        else "MISSING"
    )
    result.statuses["commands_settings"] = (
        "OK"
        if all(
            token in router + settings_router
            for token in [
                "helpdesk_vacation",
                "helpdesk_vacation_on",
                "helpdesk_vacation_off",
                "Показать новые за отпуск",
                "settings:helpdesk",
                "Vacation mode",
                "Доступ запрещён.",
            ]
        )
        else "MISSING"
    )
    result.statuses["status"] = (
        "OK"
        if all(
            token in status
            for token in [
                "vacation mode",
                "vacation_since",
                "vacation_new_since_start",
                "vacation_new_since_last_review",
                "vacation_last_reviewed",
            ]
        )
        else "MISSING"
    )
    now = datetime(2026, 6, 29, 9, 0, tzinfo=UTC)
    current_time = now
    repo = InMemoryHelpdeskVacationRepository()
    service = HelpdeskVacationService(repo, now_factory=lambda: current_time)
    await service.enable(actor_user_id=100500)
    repo.add_review_event(
        glpi_ticket_id="0047513",
        title="Выход <нового> сотрудника",
        event_type="new_ticket",
        created_at=now + timedelta(minutes=1),
        telegram_chat_id=-100123,
        work_item_id="ticket-1",
        work_item_status="waiting_ack",
    )
    first = await service.review_items(telegram_chat_id=-100123)
    rendered = format_helpdesk_vacation_review_html(first)
    current_time = now + timedelta(minutes=2)
    await service.mark_reviewed()
    second = await service.review_items(telegram_chat_id=-100123)
    result.statuses["behavior_sample"] = (
        "OK"
        if [item.glpi_ticket_id for item in first] == ["0047513"]
        and second == []
        and "Выход &lt;нового&gt; сотрудника" in rendered
        and "<нового>" not in rendered
        else "BROKEN"
    )
    result.statuses["tests"] = (
        "OK"
        if all(
            token in tests
            for token in [
                "test_vacation_state_defaults_disabled_and_toggle_is_idempotent",
                "test_vacation_on_saves_ticket_without_card_and_advances_uid",
                "test_reschedule_active_reminders_after_vacation_avoids_backlog_flood",
                "test_remind_helpdesk_tickets_vacation_on_suppresses_and_reschedules",
                "test_helpdesk_vacation_review_updates_cursor_only_after_successful_send",
                "test_status_command_shows_helpdesk_vacation_fields_without_ids",
                "test_helpdesk_vacation_readiness_passes",
            ]
        )
        else "MISSING"
    )
    result.statuses["docs"] = (
        "OK"
        if all(
            token in docs
            for token in [
                "Stage 4L-3 HelpDesk Vacation Mode",
                "Режим отпуска",
                "suppressed_vacation",
                "NO_BACKLOG_FLOOD: PASS",
                "Railway Variables не меняются",
                "не помечает письма прочитанными",
            ]
        )
        else "MISSING"
    )

    if all(status == "OK" for status in result.statuses.values()):
        result.verdict = "PASS_HELPDESK_VACATION_READINESS"
    return result


def main() -> int:
    result = asyncio.run(run_readiness())
    print(result.render_sanitized())  # noqa: T201
    return 0 if result.verdict == "PASS_HELPDESK_VACATION_READINESS" else 2


if __name__ == "__main__":
    sys.exit(main())
