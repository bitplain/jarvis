from __future__ import annotations

import asyncio
import importlib
import inspect
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from aiogram import Bot

from app.core.config import Settings

try:
    from run_polling import resolve_host_polling_settings
    from smoke_group_readiness import run_readiness as run_group_readiness
    from smoke_group_stability_readiness import run_readiness as run_group_stability_readiness
    from smoke_llm import RetryableFailingProvider, run_smoke
    from smoke_polling_readiness import run_readiness as run_polling_readiness
except ModuleNotFoundError:
    from scripts.run_polling import resolve_host_polling_settings
    from scripts.smoke_group_readiness import run_readiness as run_group_readiness
    from scripts.smoke_group_stability_readiness import (
        run_readiness as run_group_stability_readiness,
    )
    from scripts.smoke_llm import RetryableFailingProvider, run_smoke
    from scripts.smoke_polling_readiness import run_readiness as run_polling_readiness

from app.llm.fallback import FallbackLLMProvider
from app.llm.openrouter import OpenRouterProvider
from app.llm.yandex import YandexAIStudioProvider


class ReadinessBot(Protocol):
    async def get_me(self) -> object:
        ...

    @property
    def session(self) -> Any:
        ...


Probe = Callable[[], bool | str | Awaitable[bool | str]]


@dataclass
class StreamingReadinessResult:
    statuses: dict[str, str] = field(default_factory=dict)
    verdict: str = "PARTIAL_STREAMING_READINESS_NEEDS_FIX"

    def render_sanitized(self) -> str:
        lines = ["Stage 3A-S Streaming readiness sanitized result:"]
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


async def check_llm(settings: Settings) -> str:
    result = await run_smoke(
        yandex=YandexAIStudioProvider(settings),
        openrouter=OpenRouterProvider(settings),
        forced_primary=RetryableFailingProvider(),
        forced_fallback=FallbackLLMProvider(
            primary=RetryableFailingProvider(),
            fallback=OpenRouterProvider(settings),
        ),
    )
    return result.verdict


async def _check_polling(settings: Settings) -> str:
    bot = Bot(token=settings.telegram_bot_token)
    result = await run_polling_readiness(settings=settings, bot=bot)
    return result.verdict


async def _check_group(settings: Settings) -> str:
    result = await run_group_readiness(settings=settings)
    return result.verdict


def _check_group_stability() -> str:
    result = run_group_stability_readiness()
    return result.verdict


def _import_ok(module_name: str, attribute: str | None = None) -> bool:
    try:
        module = importlib.import_module(module_name)
    except Exception:
        return False
    if attribute is None:
        return True
    return hasattr(module, attribute)


async def run_readiness(
    *,
    settings: Settings,
    bot: ReadinessBot,
    llm_probe: Probe | None = None,
    polling_probe: Probe | None = None,
    group_probe: Probe | None = None,
    group_stability_probe: Probe | None = None,
) -> StreamingReadinessResult:
    result = StreamingReadinessResult()
    try:
        result.statuses["telegram_token"] = "SET" if settings.telegram_bot_token else "MISSING"
        result.statuses["admin_ids"] = (
            f"SET count={len(settings.admin_ids)}" if settings.admin_ids else "MISSING"
        )
        result.statuses["streaming_enabled"] = "true" if settings.streaming_enabled else "false"
        result.statuses["streaming_private_draft_enabled"] = (
            "true" if settings.streaming_private_draft_enabled else "false"
        )
        result.statuses["streaming_group_fallback_enabled"] = (
            "true" if settings.streaming_group_fallback_enabled else "false"
        )
        result.statuses["streaming_draft_raw_api_fallback"] = (
            "true" if settings.streaming_draft_raw_api_fallback else "false"
        )
        result.statuses["yandex_model"] = "SET" if settings.yandex_ai_model else "MISSING"
        result.statuses["openrouter_model"] = "SET" if settings.openrouter_model else "MISSING"
        result.statuses["draft_adapter_import"] = (
            "OK"
            if _import_ok("app.bot.adapters.message_draft_api", "TelegramMessageDraftApi")
            else "MISSING"
        )
        result.statuses["buffer_config"] = (
            "OK" if _import_ok("app.bot.streaming.buffer", "StreamBuffer") else "MISSING"
        )
        result.statuses["worker_import"] = (
            "OK" if _import_ok("app.workers.jobs", "process_llm_message") else "MISSING"
        )
        try:
            await bot.get_me()
            result.statuses["telegram_get_me"] = "OK"
        except Exception:
            result.statuses["telegram_get_me"] = "BLOCKED:telegram_api_error"

        llm_result = await _resolve_probe(llm_probe or (lambda: check_llm(settings)))
        polling_result = await _resolve_probe(polling_probe or (lambda: _check_polling(settings)))
        group_result = await _resolve_probe(group_probe or (lambda: _check_group(settings)))
        group_stability_result = await _resolve_probe(
            group_stability_probe or _check_group_stability
        )
        result.statuses["llm_smoke"] = str(llm_result)
        result.statuses["polling_readiness"] = str(polling_result)
        result.statuses["group_readiness"] = str(group_result)
        result.statuses["group_stability_readiness"] = str(group_stability_result)

        required_ok = (
            result.statuses["telegram_token"] == "SET"
            and result.statuses["admin_ids"].startswith("SET count=")
            and result.statuses["streaming_enabled"] == "true"
            and result.statuses["streaming_private_draft_enabled"] == "true"
            and result.statuses["streaming_group_fallback_enabled"] == "true"
            and result.statuses["streaming_draft_raw_api_fallback"] == "true"
            and result.statuses["yandex_model"] == "SET"
            and result.statuses["openrouter_model"] == "SET"
            and result.statuses["draft_adapter_import"] == "OK"
            and result.statuses["buffer_config"] == "OK"
            and result.statuses["worker_import"] == "OK"
            and result.statuses["telegram_get_me"] == "OK"
            and result.statuses["llm_smoke"] == "PASS_LLM_SMOKE"
            and result.statuses["polling_readiness"] == "PASS_POLLING_READINESS"
            and result.statuses["group_readiness"] == "PASS_GROUP_READINESS"
            and result.statuses["group_stability_readiness"] == "PASS_GROUP_STABILITY_READINESS"
        )
        if required_ok:
            result.verdict = "PASS_STREAMING_READINESS"
    finally:
        close = getattr(bot.session, "close", None)
        if close is not None:
            await close()
    return result


async def async_main() -> int:
    settings = resolve_host_polling_settings(Settings())
    if not settings.telegram_bot_token:
        print("Telegram token is not configured.")  # noqa: T201
        return 2
    bot = Bot(token=settings.telegram_bot_token)
    result = await run_readiness(settings=settings, bot=bot)
    print(result.render_sanitized())  # noqa: T201
    return 0 if result.verdict == "PASS_STREAMING_READINESS" else 2


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    sys.exit(main())
