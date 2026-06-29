from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field
from pathlib import Path

from app.services.helpdesk_imap.formatter import build_helpdesk_ticket_card
from app.services.helpdesk_imap.parser import parse_glpi_email

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class HelpdeskImapReadinessResult:
    statuses: dict[str, str] = field(default_factory=dict)
    verdict: str = "PARTIAL_HELPDESK_IMAP_READINESS_NEEDS_FIX"

    def render_sanitized(self) -> str:
        lines = ["Stage 4L HelpDesk IMAP readiness sanitized result:"]
        for key in sorted(self.statuses):
            lines.append(f"{key}: {self.statuses[key]}")
        lines.append(f"verdict: {self.verdict}")
        return "\n".join(lines)


def _read(path: str) -> str:
    target = ROOT / path
    if not target.exists():
        return ""
    return target.read_text(encoding="utf-8")


async def run_readiness() -> HelpdeskImapReadinessResult:
    result = HelpdeskImapReadinessResult()
    config = _read("app/core/config.py")
    service_files = "\n".join(
        _read(path)
        for path in [
            "app/services/helpdesk_imap/config.py",
            "app/services/helpdesk_imap/client.py",
            "app/services/helpdesk_imap/parser.py",
            "app/services/helpdesk_imap/formatter.py",
            "app/services/helpdesk_imap/service.py",
        ]
    )
    worker = _read("app/workers/arq_settings.py") + _read("app/workers/jobs.py")
    migration = (
        _read("alembic/versions/20260627_0012_helpdesk_email_events.py")
        + _read("alembic/versions/20260628_0013_helpdesk_imap_mailbox_state.py")
    )
    models = _read("app/db/models.py")
    commands = _read("app/bot/routers/commands.py")
    status = _read("app/services/status_service.py")
    config_source = _read("app/services/helpdesk_imap/config.py")
    service_source = _read("app/services/helpdesk_imap/service.py")
    docs = _read("README.md") + _read("docs/ARCHITECTURE.md") + _read("AGENTS.md")
    report = _read("docs/STAGE_4L_HELPDESK_IMAP_INBOX_REPORT.md")
    tests = "\n".join(
        _read(path)
        for path in [
            "tests/test_helpdesk_imap_config.py",
            "tests/test_helpdesk_imap_parser.py",
            "tests/test_helpdesk_imap_formatter.py",
            "tests/test_helpdesk_imap_service.py",
            "tests/test_helpdesk_imap_worker_status.py",
            "tests/test_status_command.py",
        ]
    )

    env_names = [
        "helpdesk_imap_enabled",
        "helpdesk_imap_host",
        "helpdesk_imap_port",
        "helpdesk_imap_ssl",
        "helpdesk_imap_username",
        "helpdesk_imap_password",
        "helpdesk_imap_folder",
        "helpdesk_imap_poll_interval_seconds",
        "helpdesk_imap_from_filter",
        "helpdesk_imap_subject_prefix",
        "helpdesk_telegram_chat_id",
        "helpdesk_mark_seen",
    ]
    result.statuses["config_names"] = (
        "OK" if all(name in config for name in env_names) else "MISSING"
    )
    result.statuses["service_files"] = (
        "OK"
        if all(
            token in service_files
            for token in [
                "HelpdeskImapConfig",
                "imaplib",
                "parse_glpi_email",
                "build_helpdesk_ticket_card",
                "HelpdeskImapService",
                "HelpdeskImapAuthError",
                "HelpdeskImapNetworkError",
            ]
        )
        else "MISSING"
    )
    result.statuses["worker_cron"] = (
        "OK"
        if "check_helpdesk_imap_mailbox" in worker
        and "cron(check_helpdesk_imap_mailbox)" in worker
        else "MISSING"
    )
    result.statuses["migration"] = (
        "OK"
        if all(
            token in migration + models
            for token in [
                "helpdesk_email_events",
                "helpdesk_imap_mailbox_state",
                "message_id",
                "imap_uid",
                "last_seen_uid",
                "uidvalidity",
                "baseline_at",
                "uq_helpdesk_email_events_message_id",
                "uq_helpdesk_email_events_folder_imap_uid",
                "uq_helpdesk_imap_mailbox_state_folder",
                "ix_helpdesk_email_events_notify_status",
            ]
        )
        else "MISSING"
    )
    parsed = parse_glpi_email(
        subject="[GLPI #0047513] Новая заявка",
        body=(
            "URL : https://sd.asdf.help/ticket/47513\n"
            "ФИО: Масленникова Дарья Александровна\n"
            "Должность: специалист\n"
            "Настроить доступы:\n"
            "1. почта\n"
            "2. CRM"
        ),
        from_header="Service Desk <sd@asdf.help>",
    )
    result.statuses["parser"] = (
        "OK"
        if parsed.ticket_id == "0047513"
        and parsed.employee_full_name == "Масленникова Дарья Александровна"
        and parsed.access_items == ["почта", "CRM"]
        else "BROKEN"
    )
    card = build_helpdesk_ticket_card(parsed)
    result.statuses["formatter"] = (
        "OK"
        if "<b>Заявка GLPI #0047513</b>" in card.text
        and card.reply_markup is None
        and "**" not in card.text
        else "BROKEN"
    )
    result.statuses["baseline"] = (
        "OK"
        if all(
            token in service_source
            for token in [
                "baseline_set",
                "baseline_reset",
                "fetch_since",
                "mailbox_snapshot",
                "helpdesk_imap_uidvalidity_changed",
            ]
        )
        else "MISSING"
    )
    result.statuses["baseline_command"] = (
        "OK"
        if "cmd_helpdesk_baseline_now" in commands
        and "helpdesk_baseline_now" in commands
        and "HelpDesk baseline обновлён." in commands
        else "MISSING"
    )
    result.statuses["status"] = (
        "OK"
        if "HelpDesk IMAP" in status
        and "HELPDESK_LAST_CHECK_KEY" in status
        and "helpdesk_imap" in status
        and "last_seen_uid" in status
        and "baseline" in status
        else "MISSING"
    )
    result.statuses["no_mark_seen_delete_added"] = (
        "OK"
        if "BODY.PEEK[]" in service_files
        and "delete" not in service_source.lower()
        and "connection.uid(\"store\"" not in service_source
        else "REVIEW"
    )
    result.statuses["secret_logging"] = (
        "OK"
        if "password: str = field(repr=False)" in config_source
        and "config.password" not in service_source
        and not any(
            "logger." in line and ("body" in line.lower() or "password" in line.lower())
            for line in service_source.splitlines()
        )
        else "REVIEW"
    )
    result.statuses["tests"] = (
        "OK"
        if all(
            token in tests
            for token in [
                "test_helpdesk_imap_disabled_by_default",
                "test_parse_glpi_new_ticket_email_extracts_helpdesk_fields",
                "test_helpdesk_formatter_escapes_html",
                "test_helpdesk_formatter_escapes_html_and_omits_open_button_by_default",
                "test_helpdesk_service_dedupes_same_message_id",
                "test_helpdesk_service_first_poll_sets_baseline_without_notifications",
                "test_helpdesk_service_second_poll_processes_only_new_uid_after_baseline",
                "test_helpdesk_service_uidvalidity_change_resets_baseline_without_flood",
                "test_helpdesk_baseline_now_admin_command_sets_baseline_without_notifications",
                "test_helpdesk_worker_is_registered",
            ]
        )
        else "MISSING"
    )
    result.statuses["docs"] = (
        "OK"
        if "Stage 4L HelpDesk IMAP Inbox" in docs + report
        and "HELPDESK_IMAP_ENABLED" in docs + report
        and "baseline" in docs + report
        and "без Telegram-ввода пароля" in docs + report
        else "MISSING"
    )

    if all(status == "OK" for status in result.statuses.values()):
        result.verdict = "PASS_HELPDESK_IMAP_READINESS"
    return result


def main() -> int:
    result = asyncio.run(run_readiness())
    print(result.render_sanitized())  # noqa: T201
    return 0 if result.verdict == "PASS_HELPDESK_IMAP_READINESS" else 2


if __name__ == "__main__":
    sys.exit(main())
