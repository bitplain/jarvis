from __future__ import annotations

import asyncio
import inspect
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from app.bot.dispatcher import build_dispatcher
from app.bot.routers import groups, private
from app.core.config import Settings

try:
    from run_polling import ALLOWED_UPDATES, resolve_host_polling_settings
    from smoke_polling_readiness import check_llm
    from smoke_polling_readiness import run_readiness as run_polling_readiness
except ModuleNotFoundError:
    from scripts.run_polling import ALLOWED_UPDATES, resolve_host_polling_settings
    from scripts.smoke_polling_readiness import check_llm
    from scripts.smoke_polling_readiness import run_readiness as run_polling_readiness


Probe = Callable[[], bool | str | Awaitable[bool | str]]


@dataclass
class GroupReadinessResult:
    statuses: dict[str, str] = field(default_factory=dict)
    verdict: str = "BLOCKED_GROUP_READINESS"

    def render_sanitized(self) -> str:
        lines = ["Stage 3A-R Group routing readiness sanitized result:"]
        for key in sorted(self.statuses):
            lines.append(f"{key}: {self.statuses[key]}")
        lines.append(f"verdict: {self.verdict}")
        return "\n".join(lines)


async def _resolve_probe(probe: Probe) -> bool | str:
    value = probe()
    if inspect.isawaitable(value):
        resolved = await value
        return resolved
    return value


def _has_message_handler_filter(router: object) -> bool:
    handlers = getattr(getattr(router, "message", None), "handlers", [])
    return bool(handlers and handlers[0].filters)


def _has_group_router(dispatcher: object) -> bool:
    return any(getattr(router, "name", "") == "groups" for router in dispatcher.sub_routers)


def _test_file_contains(path: str, patterns: tuple[str, ...]) -> bool:
    content = (Path(__file__).resolve().parents[1] / path).read_text(encoding="utf-8")
    return all(pattern in content for pattern in patterns)


async def _check_polling_readiness(settings: Settings) -> str:
    from aiogram import Bot

    bot = Bot(token=settings.telegram_bot_token)
    result = await run_polling_readiness(settings=settings, bot=bot)
    return result.verdict


async def run_readiness(
    *,
    settings: Settings,
    polling_readiness: Probe | None = None,
    llm_smoke: Probe | None = None,
) -> GroupReadinessResult:
    result = GroupReadinessResult()
    result.statuses["telegram_token"] = "SET" if settings.telegram_bot_token else "MISSING"
    result.statuses["telegram_username"] = "SET" if settings.telegram_bot_username else "MISSING"
    result.statuses["admin_ids"] = (
        f"SET count={len(settings.admin_ids)}" if settings.admin_ids else "MISSING"
    )
    result.statuses["group_assistant_enabled"] = (
        "true" if settings.group_assistant_enabled else "false"
    )
    result.statuses["yandex_model"] = "SET" if settings.yandex_ai_model else "MISSING"
    result.statuses["openrouter_model"] = "SET" if settings.openrouter_model else "MISSING"

    result.statuses["allowed_updates_message"] = "OK" if "message" in ALLOWED_UPDATES else "MISSING"
    dispatcher = build_dispatcher(settings)
    result.statuses["group_router_registered"] = (
        "OK" if _has_group_router(dispatcher) else "MISSING"
    )
    result.statuses["private_router_filter"] = (
        "OK" if _has_message_handler_filter(private.build_router()) else "MISSING"
    )
    result.statuses["group_router_filter"] = (
        "OK" if _has_message_handler_filter(groups.build_router()) else "MISSING"
    )
    result.statuses["group_plain_ignore_test"] = (
        "OK"
        if _test_file_contains(
            "tests/test_group_handler.py",
            ("test_group_plain_message_without_mention_is_not_saved_or_queued",),
        )
        else "MISSING"
    )
    result.statuses["group_mention_reply_test"] = (
        "OK"
        if _test_file_contains(
            "tests/test_group_handler.py",
            (
                "test_group_mention_records_message_and_enqueues_worker_job",
                "test_group_reply_to_bot_records_message_and_enqueues_worker_job",
            ),
        )
        else "MISSING"
    )

    polling_result = await _resolve_probe(
        polling_readiness or (lambda: _check_polling_readiness(settings))
    )
    llm_result = await _resolve_probe(llm_smoke or (lambda: check_llm(settings)))
    result.statuses["polling_readiness"] = str(polling_result)
    result.statuses["llm_smoke"] = str(llm_result)

    required_ok = (
        result.statuses["telegram_token"] == "SET"
        and result.statuses["telegram_username"] == "SET"
        and result.statuses["admin_ids"].startswith("SET count=")
        and result.statuses["group_assistant_enabled"] == "true"
        and result.statuses["yandex_model"] == "SET"
        and result.statuses["openrouter_model"] == "SET"
        and result.statuses["allowed_updates_message"] == "OK"
        and result.statuses["group_router_registered"] == "OK"
        and result.statuses["private_router_filter"] == "OK"
        and result.statuses["group_router_filter"] == "OK"
        and result.statuses["group_plain_ignore_test"] == "OK"
        and result.statuses["group_mention_reply_test"] == "OK"
        and result.statuses["polling_readiness"] == "PASS_POLLING_READINESS"
        and result.statuses["llm_smoke"] == "PASS_LLM_SMOKE"
    )
    if required_ok:
        result.verdict = "PASS_GROUP_READINESS"
    return result


async def async_main() -> int:
    settings = resolve_host_polling_settings(Settings())
    result = await run_readiness(settings=settings)
    print(result.render_sanitized())  # noqa: T201
    return 0 if result.verdict == "PASS_GROUP_READINESS" else 2


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    sys.exit(main())
