from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from app.services.runtime_settings_service import RuntimeSettingsService
from app.services.simple_intent_parser import ReminderCreateIntent, parse_explicit_intent

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class ListsRemindersUxReadinessResult:
    statuses: dict[str, str] = field(default_factory=dict)
    verdict: str = "PARTIAL_LISTS_REMINDERS_UX_READINESS_NEEDS_FIX"

    def render_sanitized(self) -> str:
        lines = ["Stage 4G-1 lists/reminders UX readiness sanitized result:"]
        for key in sorted(self.statuses):
            lines.append(f"{key}: {self.statuses[key]}")
        lines.append(f"verdict: {self.verdict}")
        return "\n".join(lines)


class _MemoryRuntimeSettingsRepository:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def get_value(self, key: str) -> str | None:
        return self.values.get(key)

    async def set_value(
        self,
        key: str,
        value: str,
        *,
        updated_by_telegram_id: int | None,
    ) -> None:
        del updated_by_telegram_id
        self.values[key] = value

    async def delete_value(self, key: str) -> None:
        self.values.pop(key, None)


def _read(path: str) -> str:
    target = ROOT / path
    if not target.exists():
        return ""
    return target.read_text(encoding="utf-8")


async def run_readiness() -> ListsRemindersUxReadinessResult:
    result = ListsRemindersUxReadinessResult()
    commands = _read("app/bot/routers/commands.py")
    router = _read("app/bot/routers/lists_reminders.py")
    parser = _read("app/services/simple_intent_parser.py")
    formatter = _read("app/services/telegram_formatting.py")
    runtime_settings = _read("app/services/runtime_settings_service.py")
    worker = _read("app/workers/jobs.py")
    tests = "\n".join(
        _read(path)
        for path in [
            "tests/test_runtime_settings_service.py",
            "tests/test_simple_intent_parser.py",
            "tests/test_telegram_formatting.py",
            "tests/test_telegram_webhook_ingress.py",
            "tests/test_smoke_lists_reminders_ux_readiness.py",
        ]
    )

    result.statuses["settings_section_exists"] = (
        "OK"
        if "SETTINGS_CALLBACK_LISTS" in commands
        and "Списки и напоминания" in commands
        and "Часовой пояс" in commands
        else "MISSING"
    )
    result.statuses["timezone_runtime_setting_exists"] = (
        "OK"
        if "LISTS_TIMEZONE_KEY" in runtime_settings
        and "lists.timezone" in runtime_settings
        and "get_lists_timezone" in runtime_settings
        else "MISSING"
    )
    repository = _MemoryRuntimeSettingsRepository()
    service = RuntimeSettingsService(repository)
    timezone = await service.set_lists_timezone(
        "Europe/Amsterdam",
        updated_by_telegram_id=100500,
    )
    try:
        await service.set_lists_timezone("Europe/NoSuchCity", updated_by_telegram_id=100500)
    except ValueError:
        invalid_rejected = True
    else:
        invalid_rejected = False
    result.statuses["timezone_validation_exists"] = (
        "OK"
        if getattr(timezone, "key", "") == "Europe/Amsterdam" and invalid_rejected
        else "BROKEN"
    )
    parsed = parse_explicit_intent(
        "напомни завтра в 10 купить молоко",
        timezone=timezone,
    )
    result.statuses["timezone_affects_parser"] = (
        "OK"
        if isinstance(parsed, ReminderCreateIntent)
        and getattr(parsed.remind_at.tzinfo, "key", "") == "Europe/Amsterdam"
        else "BROKEN"
    )
    result.statuses["add_list_fsm_exists"] = (
        "OK" if "ShoppingListInput" in router and "shop:add" in router else "MISSING"
    )
    result.statuses["shopping_parser_sanitizer_exists"] = (
        "OK"
        if "sanitize_shopping_items_input" in parser
        and "split_shopping_items" in parser
        and "bot_username=" in router
        else "MISSING"
    )
    result.statuses["add_reminder_fsm_exists"] = (
        "OK" if "ReminderInput" in router and "rem:add" in router else "MISSING"
    )
    result.statuses["clear_all_confirmation_exists"] = (
        "OK"
        if "shop:clear_all" in router
        and "shop:clear_all_confirm" in router
        and "Точно очистить весь список покупок?" in router
        else "MISSING"
    )
    result.statuses["help_text_exists"] = (
        "OK"
        if "format_lists_reminders_private_help_html" in formatter
        and "format_lists_reminders_group_help_html" in formatter
        and "помощь список" in parser
        else "MISSING"
    )
    forbidden = "\n".join([commands, router, parser, formatter, runtime_settings, worker]).lower()
    result.statuses["no_watcher_enabled"] = (
        "OK"
        if "watcher enabled" not in forbidden
        and "smart watcher" not in forbidden
        and "auto-read" not in forbidden
        else "BROKEN"
    )
    result.statuses["tests_exist"] = (
        "OK"
        if all(
            token in tests
            for token in [
                "test_settings_lists_reminders_screen_and_timezone_fsm",
                "test_shopping_add_button_fsm_adds_items_without_llm_job",
                "test_group_shopping_add_button_fsm_strips_bot_mention",
                "test_reminder_add_button_fsm_creates_reminder_without_llm_job",
                "test_lists_help_private_and_group_do_not_enqueue_llm",
            ]
        )
        else "MISSING"
    )

    if all(status == "OK" for status in result.statuses.values()):
        result.verdict = "PASS_LISTS_REMINDERS_UX_READINESS"
    return result


def main() -> None:
    result = asyncio.run(run_readiness())
    print(result.render_sanitized())  # noqa: T201
    if result.verdict != "PASS_LISTS_REMINDERS_UX_READINESS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
