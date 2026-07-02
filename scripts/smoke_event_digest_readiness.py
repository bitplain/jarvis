from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class EventDigestReadinessResult:
    statuses: dict[str, str] = field(default_factory=dict)
    verdict: str = "PARTIAL_EVENT_DIGEST_READINESS_NEEDS_FIX"

    def render_sanitized(self) -> str:
        lines = ["Stage 3 Event Inbox digests readiness sanitized result:"]
        for key in sorted(self.statuses):
            lines.append(f"{key}: {self.statuses[key]}")
        lines.append(f"verdict: {self.verdict}")
        return "\n".join(lines)


def _read(path: str) -> str:
    target = ROOT / path
    if not target.exists():
        return ""
    return target.read_text(encoding="utf-8")


async def run_readiness() -> EventDigestReadinessResult:
    result = EventDigestReadinessResult()
    models = _read("app/db/models.py")
    migration = _read("alembic/versions/20260701_0017_digest_policies.py")
    service = _read("app/services/digests.py")
    repository = _read("app/db/repositories/digests.py")
    event_items = _read("app/services/event_items.py") + _read(
        "app/db/repositories/event_items.py"
    )
    commands = _read("app/bot/routers/commands.py")
    worker = _read("app/workers/jobs.py")
    arq_settings = _read("app/workers/arq_settings.py")
    status = _read("app/services/status_service.py")
    docs = "\n".join([_read("README.md"), _read("docs/ARCHITECTURE.md"), _read("AGENTS.md")])
    tests = "\n".join(
        [
            _read("tests/test_event_digests.py"),
            _read("tests/test_settings_command.py"),
            _read("tests/test_worker_jobs.py"),
            _read("tests/test_status_diagnostics.py"),
            _read("tests/test_smoke_event_digest_readiness.py"),
        ]
    )

    result.statuses["model_migration"] = (
        "OK"
        if all(
            token in models + migration
            for token in [
                "class DigestPolicy",
                "digest_policies",
                "scope_filter_json",
                "personal_morning",
                "work_start",
                "Europe/Moscow",
            ]
        )
        else "MISSING"
    )
    result.statuses["default_policy_service"] = (
        "OK"
        if all(
            token in service + repository
            for token in [
                "Личный утренний дайджест",
                "Рабочий дайджест",
                "EventScope.PERSONAL",
                "EventScope.HOUSEHOLD",
                "EventScope.WORK",
                "ensure_default_policies",
            ]
        )
        else "MISSING"
    )
    result.statuses["event_scope_filter"] = (
        "OK"
        if all(
            token in event_items
            for token in [
                "list_for_digest",
                "EventItem.status == \"new\"",
                "EventItem.status == \"snoozed\"",
                "create_personal_event",
                "create_work_event",
            ]
        )
        else "MISSING"
    )
    result.statuses["settings_route"] = (
        "OK"
        if all(
            token in commands
            for token in [
                "SETTINGS_CALLBACK_DIGESTS",
                "render_digest_settings_text",
                "DigestSettingsInput",
                "Использовать этот чат",
                "cmd_digest",
            ]
        )
        else "MISSING"
    )
    result.statuses["worker_cron_and_claim"] = (
        "OK"
        if all(
            token in worker + arq_settings
            for token in [
                "send_due_digests",
                "cron(send_due_digests)",
                "digest:send:",
                "_claim_digest_send",
                "_release_digest_send_claim",
                "mark_sent_if_due",
            ]
        )
        else "MISSING"
    )
    result.statuses["status_integration"] = (
        "OK"
        if all(token in status for token in ["Digests:", "DigestPolicy", "last sent"])
        else "MISSING"
    )
    result.statuses["tests_exist"] = (
        "OK"
        if all(
            token in tests
            for token in [
                "test_default_digest_policies_are_created_with_hard_scope_filters",
                "test_digest_builder_keeps_personal_and_work_scopes_separate",
                "test_digest_settings_section_visible_to_admin",
                "test_send_due_digests_sends_and_marks_after_success",
                "test_event_digest_readiness_passes",
            ]
        )
        else "MISSING"
    )
    digest_worker = _slice_between(
        worker,
        "async def send_due_digests",
        "async def remind_helpdesk_tickets",
    )
    scoped = "\n".join([migration, service, repository, event_items, digest_worker])
    result.statuses["no_whoop_oauth_scope"] = (
        "OK"
        if "OAuth" not in scoped
        and "oauth" not in scoped
        and "WHOOP" not in scoped
        and "whoop" not in scoped.replace("whoop_sleep", "")
        else "BROKEN"
    )
    result.statuses["docs"] = (
        "OK"
        if all(
            token in docs
            for token in [
                "Stage 3 Event Inbox Digests",
                "06:50 Europe/Moscow",
                "09:00 Europe/Moscow",
                "WHOOP пока не включён",
            ]
        )
        else "MISSING"
    )

    if all(status == "OK" for status in result.statuses.values()):
        result.verdict = "PASS_EVENT_DIGEST_READINESS"
    return result


def main() -> None:
    result = asyncio.run(run_readiness())
    print(result.render_sanitized())  # noqa: T201
    if result.verdict != "PASS_EVENT_DIGEST_READINESS":
        raise SystemExit(1)


def _slice_between(text: str, start: str, end: str) -> str:
    start_index = text.find(start)
    if start_index < 0:
        return ""
    end_index = text.find(end, start_index)
    if end_index < 0:
        return text[start_index:]
    return text[start_index:end_index]


if __name__ == "__main__":
    main()
