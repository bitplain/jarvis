from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from app.services.helpdesk_imap.formatter import build_helpdesk_ticket_card
from app.services.helpdesk_imap.parser import ParsedHelpdeskTicket
from app.services.helpdesk_ticket_workflow import (
    HelpdeskTicketWorkflowService,
    InMemoryHelpdeskTicketWorkItemRepository,
    build_in_work_keyboard,
    format_helpdesk_ticket_reminder_html,
)

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class HelpdeskTicketWorkflowReadinessResult:
    statuses: dict[str, str] = field(default_factory=dict)
    verdict: str = "PARTIAL_HELPDESK_TICKET_WORKFLOW_READINESS_NEEDS_FIX"

    def render_sanitized(self) -> str:
        lines = ["Stage 4L-2 HelpDesk ticket workflow readiness sanitized result:"]
        for key in sorted(self.statuses):
            lines.append(f"{key}: {self.statuses[key]}")
        lines.append(f"verdict: {self.verdict}")
        return "\n".join(lines)


def _read(path: str) -> str:
    target = ROOT / path
    if not target.exists():
        return ""
    return target.read_text(encoding="utf-8")


async def run_readiness() -> HelpdeskTicketWorkflowReadinessResult:
    result = HelpdeskTicketWorkflowReadinessResult()
    models = _read("app/db/models.py")
    migration = _read("alembic/versions/20260629_0014_helpdesk_ticket_work_items.py")
    repository = _read("app/db/repositories/helpdesk_ticket_work_items.py")
    service = _read("app/services/helpdesk_ticket_workflow.py")
    formatter = _read("app/services/helpdesk_imap/formatter.py")
    imap_service = _read("app/services/helpdesk_imap/service.py")
    router = _read("app/bot/routers/helpdesk_tickets.py")
    dispatcher = _read("app/bot/dispatcher.py")
    worker = _read("app/workers/jobs.py") + _read("app/workers/arq_settings.py")
    docs = "\n".join(
        [
            _read("AGENTS.md"),
            _read("README.md"),
            _read("docs/ARCHITECTURE.md"),
            _read("docs/STAGE_4L_HELPDESK_IMAP_INBOX_REPORT.md"),
            _read("docs/STAGE_4L2_HELPDESK_TICKET_WORKFLOW_REPORT.md"),
        ]
    )
    tests = "\n".join(
        [
            _read("tests/test_helpdesk_ticket_workflow_service.py"),
            _read("tests/test_helpdesk_ticket_workflow_router.py"),
            _read("tests/test_helpdesk_imap_formatter.py"),
            _read("tests/test_helpdesk_imap_service.py"),
            _read("tests/test_worker_jobs.py"),
            _read("tests/test_smoke_helpdesk_ticket_workflow_readiness.py"),
        ]
    )

    result.statuses["model_migration"] = (
        "OK"
        if all(
            token in models + migration
            for token in [
                "helpdesk_ticket_work_items",
                "glpi_ticket_id",
                "latest_event_id",
                "waiting_ack",
                "in_work",
                "done",
                "dismissed",
                "uq_helpdesk_ticket_work_items_ticket_chat",
                "ix_helpdesk_ticket_work_items_status_next",
            ]
        )
        else "MISSING"
    )
    result.statuses["repository"] = (
        "OK"
        if all(
            token in repository
            for token in [
                "upsert_waiting_ack",
                "list_in_work",
                "mark_done",
                "snooze",
                "due_reminders",
                "mark_reminded",
                "with_for_update(skip_locked=True)",
            ]
        )
        else "MISSING"
    )
    result.statuses["service_rules"] = (
        "OK"
        if all(
            token in service
            for token in [
                "WAITING_ACK_INTERVAL_MINUTES = 10",
                "IN_WORK_INTERVAL_MINUTES = 30",
                "create_or_update_waiting_ack",
                "build_waiting_ack_keyboard",
                "build_in_work_keyboard",
                "format_helpdesk_ticket_reminder_html",
                "format_helpdesk_in_work_list_html",
            ]
        )
        else "MISSING"
    )
    parsed = ParsedHelpdeskTicket(
        ticket_id="0047513",
        event_type="new_ticket",
        ticket_url=None,
        title="Выход <нового> сотрудника",
        employee_full_name=None,
        position=None,
        manager=None,
        start_date=None,
        access_items=[],
        comment_count=None,
        task_count=None,
        sender_name=None,
        sender_email_masked=None,
        raw_excerpt="",
        parse_status="parsed",
    )
    card = build_helpdesk_ticket_card(parsed, work_item_id="work-123")
    button = card.reply_markup.inline_keyboard[0][0] if card.reply_markup else None
    result.statuses["new_ticket_card_button"] = (
        "OK"
        if button is not None
        and button.text == "В работу"
        and button.callback_data == "hd_ticket:take:work-123"
        and "<нового>" not in card.text
        else "BROKEN"
    )
    result.statuses["imap_integration"] = (
        "OK"
        if all(
            token in imap_service + formatter
            for token in [
                "ticket_work_repository",
                "upsert_waiting_ack",
                "work_item_id",
                "helpdesk_ticket_work_item_upsert_failed",
            ]
        )
        else "MISSING"
    )
    result.statuses["router_command_and_callbacks"] = (
        "OK"
        if all(
            token in router + dispatcher
            for token in [
                'HELPDESK_TICKET_COMMANDS = ("ticket",)',
                'action == "take"',
                'action == "done"',
                'action == "snooze"',
                "hd_ticket:",
                "handle_helpdesk_ticket_callback",
                "helpdesk_tickets.build_router()",
                "Доступ запрещён.",
            ]
        )
        else "MISSING"
    )
    result.statuses["worker_cron"] = (
        "OK"
        if all(
            token in worker
            for token in [
                "remind_helpdesk_tickets",
                "cron(remind_helpdesk_tickets)",
                "helpdesk_ticket:reminder:",
                "HELPDESK_TICKET_REMINDER_CLAIM_TTL_SECONDS",
                "helpdesk_ticket_reminder_send_failed",
                "mark_reminded",
            ]
        )
        else "MISSING"
    )
    repository_memory = InMemoryHelpdeskTicketWorkItemRepository()
    workflow = HelpdeskTicketWorkflowService(
        repository_memory,
        now_factory=lambda: datetime(2026, 6, 29, 9, 0, tzinfo=UTC),
    )
    item = await workflow.create_or_update_waiting_ack(
        glpi_ticket_id="0047513",
        latest_event_id=None,
        title="Выход <нового> сотрудника",
        telegram_chat_id=-100123,
    )
    due_waiting = await workflow.due_reminders(datetime(2026, 6, 29, 9, 10, tzinfo=UTC))
    taken = await workflow.take(item.id, actor_user_id=100500, telegram_chat_id=-100123)
    in_work_keyboard = build_in_work_keyboard(item.id)
    await workflow.mark_reminded(item.id, now=datetime(2026, 6, 29, 9, 30, tzinfo=UTC))
    result.statuses["behavior_sample"] = (
        "OK"
        if [due.id for due in due_waiting] == [item.id]
        and taken is not None
        and taken.status == "in_work"
        and repository_memory.items[item.id].next_reminder_at
        == datetime(2026, 6, 29, 10, 0, tzinfo=UTC)
        and "В работе" not in format_helpdesk_ticket_reminder_html(repository_memory.items[item.id])
        and in_work_keyboard.inline_keyboard[0][0].text == "Готово"
        and in_work_keyboard.inline_keyboard[0][1].text == "Отложить 1ч"
        else "BROKEN"
    )
    result.statuses["tests"] = (
        "OK"
        if all(
            token in tests
            for token in [
                "test_new_ticket_creates_waiting_ack_work_item_and_dedupes_same_glpi_ticket",
                "test_done_ticket_is_not_reopened_by_duplicate_email_for_same_glpi_ticket",
                "test_take_list_snooze_done_and_due_reminder_intervals",
                "test_ticket_command_shows_in_work_tickets_and_escapes_html",
                "test_ticket_callbacks_are_access_gated",
                "test_helpdesk_service_creates_waiting_work_item_before_new_ticket_card",
                "test_remind_helpdesk_tickets_send_failure_does_not_advance_reminder",
                "test_helpdesk_ticket_workflow_readiness_passes",
            ]
        )
        else "MISSING"
    )
    result.statuses["safety_docs"] = (
        "OK"
        if all(
            token in docs
            for token in [
                "Stage 4L-2 HelpDesk Ticket Workflow",
                "/ticket",
                "В работу",
                "Готово",
                "Отложить 1ч",
                "NO_EMAIL_DESTRUCTIVE_ACTIONS: PASS",
            ]
        )
        and "Railway Variables не меняются" in docs
        and "другие алиасы не добавляются" in docs.lower()
        else "MISSING"
    )
    result.statuses["no_email_destructive_actions"] = (
        "OK"
        if "mark_seen" not in service + router
        and "delete" not in service.lower() + router.lower()
        and "email replies" not in service.lower()
        else "REVIEW"
    )

    if all(status == "OK" for status in result.statuses.values()):
        result.verdict = "PASS_HELPDESK_TICKET_WORKFLOW_READINESS"
    return result


def main() -> int:
    result = asyncio.run(run_readiness())
    print(result.render_sanitized())  # noqa: T201
    return 0 if result.verdict == "PASS_HELPDESK_TICKET_WORKFLOW_READINESS" else 2


if __name__ == "__main__":
    sys.exit(main())
