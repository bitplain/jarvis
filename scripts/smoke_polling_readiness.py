from __future__ import annotations

import asyncio
import inspect
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

import redis.asyncio as redis
from aiogram import Bot
from sqlalchemy.sql import text

from app.core.config import Settings
from app.db.session import make_engine
from app.llm.fallback import FallbackLLMProvider
from app.llm.openrouter import OpenRouterProvider
from app.llm.yandex import YandexAIStudioProvider

try:
    from run_polling import resolve_host_polling_settings
    from smoke_llm import RetryableFailingProvider, run_smoke
except ModuleNotFoundError:
    from scripts.run_polling import resolve_host_polling_settings
    from scripts.smoke_llm import RetryableFailingProvider, run_smoke


class ReadinessBot(Protocol):
    async def delete_webhook(self, *, drop_pending_updates: bool) -> object:
        ...

    async def get_me(self) -> object:
        ...

    @property
    def session(self) -> Any:
        ...


Probe = Callable[[], bool | str | Awaitable[bool | str]]


@dataclass
class PollingReadinessResult:
    statuses: dict[str, str] = field(default_factory=dict)
    verdict: str = "BLOCKED_POLLING_READINESS"

    def render_sanitized(self) -> str:
        lines = ["Stage 2R polling readiness sanitized result:"]
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


async def check_postgres(settings: Settings) -> bool:
    engine = make_engine(settings)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
    finally:
        await engine.dispose()


async def check_redis(settings: Settings) -> bool:
    client = redis.from_url(settings.redis_url)  # type: ignore[no-untyped-call]
    try:
        return bool(await client.ping())
    except Exception:
        return False
    finally:
        await client.aclose()


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


async def run_readiness(
    *,
    settings: Settings,
    bot: ReadinessBot,
    postgres_probe: Probe | None = None,
    redis_probe: Probe | None = None,
    llm_smoke: Probe | None = None,
) -> PollingReadinessResult:
    result = PollingReadinessResult()
    try:
        result.statuses["telegram_token"] = "SET" if settings.telegram_bot_token else "MISSING"
        result.statuses["telegram_username"] = (
            "SET" if settings.telegram_bot_username else "MISSING"
        )
        result.statuses["admin_ids"] = (
            f"SET count={len(settings.admin_ids)}" if settings.admin_ids else "MISSING"
        )
        result.statuses["guest_mode_enabled"] = (
            "true" if settings.guest_mode_enabled else "false"
        )
        result.statuses["guest_mode_admin_only"] = (
            "true" if settings.guest_mode_admin_only else "false"
        )
        result.statuses["yandex_model"] = "SET" if settings.yandex_ai_model else "MISSING"
        result.statuses["openrouter_model"] = (
            "SET" if settings.openrouter_model else "MISSING"
        )

        if settings.app_env.lower() == "production":
            result.statuses["delete_webhook"] = "SKIPPED production_webhook_runtime"
            result.statuses["telegram_get_me"] = "SKIPPED production_webhook_runtime"
            return result

        try:
            await bot.delete_webhook(drop_pending_updates=False)
            result.statuses["delete_webhook"] = "OK drop_pending_updates=false"
            await bot.get_me()
            result.statuses["telegram_get_me"] = "OK"
        except Exception:
            result.statuses["telegram_get_me"] = "BLOCKED:telegram_api_error"

        postgres_ok = await _resolve_probe(postgres_probe or (lambda: check_postgres(settings)))
        redis_ok = await _resolve_probe(redis_probe or (lambda: check_redis(settings)))
        llm_result = await _resolve_probe(llm_smoke or (lambda: check_llm(settings)))

        result.statuses["postgres"] = "OK" if postgres_ok is True else str(postgres_ok)
        result.statuses["redis"] = "OK" if redis_ok is True else str(redis_ok)
        result.statuses["llm_smoke"] = str(llm_result)

        env_ready = (
            bool(settings.telegram_bot_token)
            and bool(settings.admin_ids)
            and settings.guest_mode_enabled
            and settings.guest_mode_admin_only
            and bool(settings.yandex_ai_model)
            and bool(settings.openrouter_model)
        )
        checks_ready = (
            result.statuses.get("telegram_get_me") == "OK"
            and result.statuses["postgres"] == "OK"
            and result.statuses["redis"] == "OK"
            and result.statuses["llm_smoke"] == "PASS_LLM_SMOKE"
        )
        if env_ready and checks_ready:
            result.verdict = "PASS_POLLING_READINESS"
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
    return 0 if result.verdict == "PASS_POLLING_READINESS" else 2


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    sys.exit(main())
