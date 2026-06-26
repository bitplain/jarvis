from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from app.services.shopping_service import ShoppingItemView, ShoppingListView
from app.services.simple_intent_parser import ShoppingAddIntent, parse_explicit_intent
from app.services.telegram_formatting import format_shopping_list_html

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class ListsRemindersReadinessResult:
    statuses: dict[str, str] = field(default_factory=dict)
    verdict: str = "PARTIAL_LISTS_REMINDERS_READINESS_NEEDS_FIX"

    def render_sanitized(self) -> str:
        lines = ["Stage 4G lists/reminders readiness sanitized result:"]
        for key in sorted(self.statuses):
            lines.append(f"{key}: {self.statuses[key]}")
        lines.append(f"verdict: {self.verdict}")
        return "\n".join(lines)


def _read(path: str) -> str:
    target = ROOT / path
    if not target.exists():
        return ""
    return target.read_text(encoding="utf-8")


async def run_readiness() -> ListsRemindersReadinessResult:
    result = ListsRemindersReadinessResult()
    migration = _read("alembic/versions/20260626_0008_lists_reminders.py")
    parser = _read("app/services/simple_intent_parser.py")
    formatter = _read("app/services/telegram_formatting.py")
    router = _read("app/bot/routers/lists_reminders.py")
    dispatcher = _read("app/bot/dispatcher.py")
    worker = _read("app/workers/jobs.py")
    arq_settings = _read("app/workers/arq_settings.py")
    tests = "\n".join(
        _read(path)
        for path in [
            "tests/test_simple_intent_parser.py",
            "tests/test_telegram_formatting.py",
            "tests/test_shopping_service.py",
            "tests/test_reminder_service.py",
            "tests/test_telegram_webhook_ingress.py",
            "tests/test_worker_jobs.py",
        ]
    )

    result.statuses["migration_exists"] = (
        "OK"
        if all(
            token in migration
            for token in ["shopping_lists", "shopping_list_items", "reminders", "20260626_0008"]
        )
        else "MISSING"
    )
    result.statuses["parser_exists"] = (
        "OK"
        if all(
            token in parser
            for token in ["ShoppingAddIntent", "ReminderCreateIntent", "Europe/Moscow"]
        )
        else "MISSING"
    )
    parsed = parse_explicit_intent("добавь хлеб в список покупок")
    result.statuses["parser_smoke"] = (
        "OK" if isinstance(parsed, ShoppingAddIntent) and parsed.items == ["хлеб"] else "BROKEN"
    )
    escaped = format_shopping_list_html(
        ShoppingListView(
            scope_type="private",
            scope_chat_id=1,
            title="Список покупок",
            active=[ShoppingItemView(id="1", text="<script> & milk", status="active")],
            done=[],
        )
    )
    result.statuses["html_escapes_user_text"] = (
        "OK" if "&lt;script&gt; &amp; milk" in escaped and "<script>" not in escaped else "BROKEN"
    )
    result.statuses["html_formatter_exists"] = (
        "OK"
        if "html import escape" in formatter and 'parse_mode="HTML"' not in formatter
        else "MISSING"
    )
    lists_router_index = dispatcher.find("lists_reminders.build_router()")
    private_router_index = dispatcher.find("private.build_router()")
    groups_router_index = dispatcher.find("groups.build_router()")
    result.statuses["routers_registered_before_generic_llm"] = (
        "OK"
        if lists_router_index < private_router_index < groups_router_index
        else "BROKEN"
    )
    result.statuses["callbacks_exist"] = (
        "OK"
        if all(
            token in router
            for token in ["shop:done:", "shop:restore:", "rem:snooze10:", "rem:snooze60:"]
        )
        else "MISSING"
    )
    result.statuses["reminder_worker_exists"] = (
        "OK"
        if "deliver_due_reminders" in worker
        and "reminder_due_delivery_started" in worker
        and "cron(deliver_due_reminders" in arq_settings
        else "MISSING"
    )
    forbidden = "\n".join([router, parser, worker, arq_settings]).lower()
    result.statuses["no_business_checklist_dependency"] = (
        "OK" if "checklist" not in forbidden and "business checklist" not in forbidden else "BROKEN"
    )
    result.statuses["tests_exist"] = (
        "OK"
        if all(
            token in tests
            for token in [
                "test_parse_shopping_add_single_item",
                "test_format_shopping_list_escapes_user_text",
                "test_private_shopping_add_returns_html_without_llm_job",
                "test_deliver_due_reminders_sends_html_and_marks_sent",
            ]
        )
        else "MISSING"
    )

    if all(status == "OK" for status in result.statuses.values()):
        result.verdict = "PASS_LISTS_REMINDERS_READINESS"
    return result


def main() -> None:
    result = asyncio.run(run_readiness())
    print(result.render_sanitized())  # noqa: T201
    if result.verdict != "PASS_LISTS_REMINDERS_READINESS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
