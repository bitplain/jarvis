from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from app.services.shopping_service import parse_shopping_item

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class DailyBriefShoppingV2ReadinessResult:
    statuses: dict[str, str] = field(default_factory=dict)
    verdict: str = "PARTIAL_DAILY_BRIEF_SHOPPING_V2_READINESS_NEEDS_FIX"

    def render_sanitized(self) -> str:
        lines = ["Stage 4J daily brief + shopping v2 readiness sanitized result:"]
        for key in sorted(self.statuses):
            lines.append(f"{key}: {self.statuses[key]}")
        lines.append(f"verdict: {self.verdict}")
        return "\n".join(lines)


def _read(path: str) -> str:
    target = ROOT / path
    if not target.exists():
        return ""
    return target.read_text(encoding="utf-8")


async def run_readiness() -> DailyBriefShoppingV2ReadinessResult:
    result = DailyBriefShoppingV2ReadinessResult()
    migration = _read("alembic/versions/20260627_0010_daily_brief_shopping_v2.py")
    models = _read("app/db/models.py")
    formatter = _read("app/services/telegram_formatting.py")
    brief_service = _read("app/services/daily_brief_service.py")
    brief_repo = _read("app/db/repositories/daily_brief.py")
    daily_router = _read("app/bot/routers/daily_brief.py")
    commands = _read("app/bot/routers/commands.py")
    dispatcher = _read("app/bot/dispatcher.py")
    worker = _read("app/workers/jobs.py")
    arq_settings = _read("app/workers/arq_settings.py")
    tests = "\n".join(
        _read(path)
        for path in [
            "tests/test_shopping_service.py",
            "tests/test_daily_brief_service.py",
            "tests/test_telegram_formatting.py",
            "tests/test_settings_command.py",
            "tests/test_worker_jobs.py",
        ]
    )

    result.statuses["migration_exists"] = (
        "OK"
        if all(
            token in migration
            for token in [
                "20260627_0010",
                "quantity",
                "unit",
                "note",
                "category",
                "daily_brief_settings",
                "last_sent_date",
            ]
        )
        else "MISSING"
    )
    result.statuses["models_exist"] = (
        "OK"
        if all(
            token in models
            for token in ["class DailyBriefSettings", "class ShoppingListItem", "quantity"]
        )
        else "MISSING"
    )
    milk = parse_shopping_item("молоко 2.5% 2 бутылки")
    result.statuses["shopping_v2_parser"] = (
        "OK"
        if milk.text == "молоко"
        and milk.quantity == 2
        and milk.unit == "бутылки"
        and milk.note == "2.5%"
        and milk.category == "Молочка"
        else "BROKEN"
    )
    result.statuses["shopping_display_groups_categories"] = (
        "OK"
        if all(
            token in formatter
            for token in ["_group_shopping_items", "🥛", "format_daily_brief_html"]
        )
        else "MISSING"
    )
    result.statuses["daily_brief_service_exists"] = (
        "OK"
        if all(
            token in brief_service + brief_repo
            for token in ["DailyBriefService", "DailyBriefSettingsRepository", "due_for_delivery"]
        )
        else "MISSING"
    )
    result.statuses["daily_brief_router_registered"] = (
        "OK"
        if "daily_brief.build_router()" in dispatcher
        and "DAILY_BRIEF_COMMANDS" in daily_router
        and "сводка дня" in daily_router
        else "MISSING"
    )
    result.statuses["settings_ui_exists"] = (
        "OK"
        if all(
            token in commands
            for token in [
                "SETTINGS_CALLBACK_DAILY_BRIEF",
                "render_daily_brief_settings_text",
                "DailyBriefSettingsInput",
                "Показать сейчас",
            ]
        )
        else "MISSING"
    )
    result.statuses["worker_cron_registered"] = (
        "OK"
        if "deliver_daily_briefs" in worker and "cron(deliver_daily_briefs" in arq_settings
        else "MISSING"
    )
    forbidden = "\n".join([brief_service, daily_router, commands, worker, arq_settings]).lower()
    result.statuses["no_watcher_voice_business_scope"] = (
        "OK"
        if all(token not in forbidden for token in ["transcription", "voice", "auto-reading"])
        and "business_connection_id" not in forbidden
        else "BROKEN"
    )
    result.statuses["tests_exist"] = (
        "OK"
        if all(
            token in tests
            for token in [
                "test_parse_shopping_v2_quantity_note_and_category",
                "test_daily_brief_private_scope_includes_reminders_shopping_and_memory",
                "test_format_shopping_list_groups_v2_items_by_category",
                "test_daily_brief_worker_is_registered",
            ]
        )
        else "MISSING"
    )

    if all(status == "OK" for status in result.statuses.values()):
        result.verdict = "PASS_DAILY_BRIEF_SHOPPING_V2_READINESS"
    return result


def main() -> None:
    result = asyncio.run(run_readiness())
    print(result.render_sanitized())  # noqa: T201
    if result.verdict != "PASS_DAILY_BRIEF_SHOPPING_V2_READINESS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
