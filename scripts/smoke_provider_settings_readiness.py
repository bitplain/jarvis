from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field
from pathlib import Path

from app.db.models import RuntimeSetting
from app.services.runtime_settings_service import (
    ACTIVE_LLM_PROVIDER_KEY,
    ActiveLLMProvider,
    RuntimeSettingsService,
)

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class ProviderSettingsReadinessResult:
    statuses: dict[str, str] = field(default_factory=dict)
    verdict: str = "PARTIAL_PROVIDER_SETTINGS_READINESS_NEEDS_FIX"

    def render_sanitized(self) -> str:
        lines = ["Stage 4D provider settings readiness sanitized result:"]
        for key in sorted(self.statuses):
            lines.append(f"{key}: {self.statuses[key]}")
        lines.append(f"verdict: {self.verdict}")
        return "\n".join(lines)


class InMemoryRuntimeSettingsRepository:
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


def _read(path: str) -> str:
    target = ROOT / path
    if not target.exists():
        return ""
    return target.read_text(encoding="utf-8")


async def run_readiness() -> ProviderSettingsReadinessResult:
    result = ProviderSettingsReadinessResult()
    repository = InMemoryRuntimeSettingsRepository()
    service = RuntimeSettingsService(repository)

    result.statuses["model"] = (
        "OK"
        if RuntimeSetting.__tablename__ == "runtime_settings"
        and hasattr(RuntimeSetting, "updated_by_telegram_id")
        else "MISSING"
    )
    migration = _read("alembic/versions/20260625_0004_runtime_settings.py")
    result.statuses["migration"] = (
        "OK"
        if "runtime_settings" in migration and "updated_by_telegram_id" in migration
        else "MISSING"
    )
    result.statuses["default_provider"] = (
        "OK" if await service.get_active_llm_provider() == ActiveLLMProvider.AUTO else "BROKEN"
    )
    accepted: list[str] = []
    for provider in ActiveLLMProvider:
        saved = await service.set_active_llm_provider(
            provider.value,
            updated_by_telegram_id=None,
        )
        if saved == provider and repository.values[ACTIVE_LLM_PROVIDER_KEY] == provider.value:
            accepted.append(provider.value)
    result.statuses["valid_values"] = (
        "OK" if accepted == ["auto", "yandex", "openrouter"] else "BROKEN"
    )
    try:
        await service.set_active_llm_provider("bad-provider", updated_by_telegram_id=None)
    except ValueError:
        result.statuses["invalid_value"] = "OK"
    else:
        result.statuses["invalid_value"] = "BROKEN"

    commands = _read("app/bot/routers/commands.py")
    required_callbacks = [
        "settings:provider:auto",
        "settings:provider:yandex",
        "settings:provider:openrouter",
        "settings:refresh",
        "settings:close",
    ]
    result.statuses["callback_ids"] = (
        "OK" if all(callback_id in commands for callback_id in required_callbacks) else "MISSING"
    )
    result.statuses["message_not_modified_guard"] = (
        "OK"
        if "message is not modified" in commands and "TelegramBadRequest" in commands
        else "MISSING"
    )
    result.statuses["close_callback"] = (
        "OK"
        if "Настройки закрыты." in commands and "settings:close" in commands
        else "MISSING"
    )
    docs = "\n".join(
        [
            _read("README.md"),
            _read("docs/ARCHITECTURE.md"),
            _read("docs/RAILWAY_DEPLOY.md"),
            _read("docs/STAGE_4D_PROVIDER_SETTINGS_REPORT.md"),
            _read("docs/STAGE_4E_RAILWAY_MIGRATION_SETTINGS_FIX_REPORT.md"),
        ]
    )
    required_docs = [
        "active_llm_provider",
        "/settings",
        "PostgreSQL runtime setting",
        "PASS_STAGE_4D_PROVIDER_SETTINGS_READY",
        "PASS_STAGE_4E_RAILWAY_MIGRATION_SETTINGS_FIX_READY",
    ]
    result.statuses["docs"] = (
        "OK" if all(item in docs for item in required_docs) else "MISSING"
    )

    if all(value == "OK" for value in result.statuses.values()):
        result.verdict = "PASS_PROVIDER_SETTINGS_READINESS"
    return result


def main() -> int:
    result = asyncio.run(run_readiness())
    print(result.render_sanitized())  # noqa: T201
    return 0 if result.verdict == "PASS_PROVIDER_SETTINGS_READINESS" else 2


if __name__ == "__main__":
    sys.exit(main())
