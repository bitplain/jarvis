from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field
from pathlib import Path

from app.db.models import TelegramAccessEntry
from app.services.telegram_access_service import TelegramAccessService

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class AccessSettingsReadinessResult:
    statuses: dict[str, str] = field(default_factory=dict)
    verdict: str = "PARTIAL_ACCESS_SETTINGS_READINESS_NEEDS_FIX"

    def render_sanitized(self) -> str:
        lines = ["Stage 4F-1 access settings readiness sanitized result:"]
        for key in sorted(self.statuses):
            lines.append(f"{key}: {self.statuses[key]}")
        lines.append(f"verdict: {self.verdict}")
        return "\n".join(lines)


class InMemoryTelegramAccessRepository:
    def __init__(self) -> None:
        self.entries: dict[tuple[str, int], object] = {}

    async def get_entry(self, entry_type: str, telegram_id: int) -> object | None:
        return self.entries.get((entry_type, telegram_id))

    async def list_entries(self, entry_type: str) -> list[object]:
        return [
            entry
            for (stored_type, _), entry in sorted(self.entries.items())
            if stored_type == entry_type
        ]

    async def upsert_entry(
        self,
        *,
        entry_type: str,
        telegram_id: int,
        label: str | None,
        created_by: int | None,
    ) -> None:
        from app.services.telegram_access_service import AccessEntry

        self.entries[(entry_type, telegram_id)] = AccessEntry(
            entry_type=entry_type,
            telegram_id=telegram_id,
            label=label,
            created_by=created_by,
        )

    async def delete_entry(self, entry_type: str, telegram_id: int) -> bool:
        return self.entries.pop((entry_type, telegram_id), None) is not None


def _read(path: str) -> str:
    target = ROOT / path
    if not target.exists():
        return ""
    return target.read_text(encoding="utf-8")


async def run_readiness() -> AccessSettingsReadinessResult:
    result = AccessSettingsReadinessResult()
    repository = InMemoryTelegramAccessRepository()
    service = TelegramAccessService(repository, admin_ids={100500})  # type: ignore[arg-type]

    result.statuses["model"] = (
        "OK"
        if TelegramAccessEntry.__tablename__ == "telegram_access_entries"
        and hasattr(TelegramAccessEntry, "telegram_id")
        and hasattr(TelegramAccessEntry, "entry_type")
        else "MISSING"
    )
    migration = _read("alembic/versions/20260625_0005_telegram_access_entries.py")
    result.statuses["migration"] = (
        "OK"
        if "telegram_access_entries" in migration
        and "uq_telegram_access_entries_entry_type_telegram_id" in migration
        and "BigInteger" in migration
        else "MISSING"
    )
    await service.add_allowed_user(200600, "Тест", created_by=100500)
    await service.add_allowed_group(-100123, "Тестовая группа", created_by=100500)
    result.statuses["service"] = (
        "OK"
        if service.is_admin_user(100500)
        and await service.is_allowed_user(100500)
        and await service.is_allowed_user(200600)
        and await service.is_allowed_group(-100123)
        else "BROKEN"
    )

    commands = _read("app/bot/routers/commands.py")
    result.statuses["whoami"] = (
        "OK" if "Command(\"whoami\")" in commands and "Ваш Telegram ID" in commands else "MISSING"
    )
    required_callbacks = [
        "settings:access",
        "settings:access:users",
        "settings:access:groups",
        "settings:access:user:add",
        "settings:access:user:remove",
        "settings:access:group:add",
        "settings:access:group:remove",
    ]
    result.statuses["access_callbacks"] = (
        "OK" if all(callback_id in commands for callback_id in required_callbacks) else "MISSING"
    )
    result.statuses["fsm_handlers"] = (
        "OK"
        if "StateFilter(TelegramAccessInput.add_user)" in commands
        and "StateFilter(TelegramAccessInput.remove_user)" in commands
        and "StateFilter(TelegramAccessInput.add_group)" in commands
        and "StateFilter(TelegramAccessInput.remove_group)" in commands
        else "MISSING"
    )
    telegram_route = _read("app/api/routes_telegram.py")
    result.statuses["persistent_dispatcher"] = (
        "OK"
        if "request.app.state.dispatcher = dispatcher" in telegram_route
        and "dispatcher is None" in telegram_route
        else "MISSING"
    )
    tests = "\n".join(
        [
            _read("tests/test_telegram_access_service.py"),
            _read("tests/test_access_control.py"),
            _read("tests/test_settings_command.py"),
            _read("tests/test_telegram_webhook_ingress.py"),
            _read("tests/test_access_settings_fsm_ingress.py"),
        ]
    )
    required_tests = [
        "test_env_admin_is_admin_and_allowed",
        "test_private_db_allowed_user_reaches_handler",
        "test_access_section_visible_to_admin",
        "test_webhook_group_db_allowed_user_mention_enqueues_once",
        "test_add_user_state_intercepts_text_before_private_llm",
        "test_invalid_access_fsm_input_does_not_enqueue_llm",
        "test_add_user_state_supports_multiple_ids_space_separated",
    ]
    result.statuses["tests"] = (
        "OK" if all(test_name in tests for test_name in required_tests) else "MISSING"
    )
    docs = "\n".join(
        [
            _read("README.md"),
            _read("docs/ARCHITECTURE.md"),
            _read("docs/STAGE_4F1_ACCESS_SETTINGS_REPORT.md"),
            _read("docs/HOTFIX_ACCESS_SETTINGS_FSM_INPUT_REPORT.md"),
            _read("AGENTS.md"),
        ]
    )
    required_docs = [
        "Stage 4F-1",
        "/whoami",
        "/settings -> Доступ",
        "telegram_access_entries",
    ]
    result.statuses["docs_report"] = (
        "OK" if all(item in docs for item in required_docs) else "MISSING"
    )
    polling_script = _read("scripts/run_polling.py")
    result.statuses["production_delete_webhook_guard"] = (
        "OK"
        if "ensure_not_production_webhook_runtime" in polling_script
        and "deleteWebhook" not in polling_script
        else "MISSING"
    )

    if all(value == "OK" for value in result.statuses.values()):
        result.verdict = "PASS_ACCESS_SETTINGS_READINESS"
    return result


def main() -> int:
    result = asyncio.run(run_readiness())
    print(result.render_sanitized())  # noqa: T201
    return 0 if result.verdict == "PASS_ACCESS_SETTINGS_READINESS" else 2


if __name__ == "__main__":
    sys.exit(main())
