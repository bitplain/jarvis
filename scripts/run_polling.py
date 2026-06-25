from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections.abc import Sequence
from typing import Any, Protocol

from aiogram import BaseMiddleware, Bot, Dispatcher
from arq import create_pool
from arq.connections import RedisSettings
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.dispatcher import build_dispatcher
from app.core.config import Settings
from app.db.session import make_engine

ALLOWED_UPDATES = [
    "business_connection",
    "business_message",
    "edited_business_message",
    "deleted_business_messages",
    "guest_message",
    "message",
    "edited_message",
    "callback_query",
]

logger = logging.getLogger(__name__)
PRODUCTION_POLLING_ERROR = "Polling is disabled in production webhook runtime."


class PollingBot(Protocol):
    async def delete_webhook(self, *, drop_pending_updates: bool) -> object:
        ...

    @property
    def session(self) -> Any:
        ...


class PollingDispatcher(Protocol):
    async def start_polling(self, bot: PollingBot, **kwargs: Any) -> object:
        ...


class PollingDatabaseSessionMiddleware(BaseMiddleware):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def __call__(self, handler: Any, event: Any, data: dict[str, Any]) -> Any:
        async with self.session_factory() as session:
            data["db_session"] = session
            return await handler(event, data)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Jarvis Telegram bot in local polling mode.")
    parser.add_argument(
        "--drop-pending-updates",
        action="store_true",
        help="Delete pending Telegram updates before polling. Default: false.",
    )
    return parser.parse_args(argv)


def resolve_host_polling_settings(settings: Settings) -> Settings:
    updates: dict[str, str] = {}
    if settings.postgres_host == "postgres":
        updates["postgres_host"] = "localhost"
    if settings.redis_url == "redis://redis:6379/0":
        updates["redis_url"] = "redis://localhost:6379/0"
    if not updates:
        return settings
    return settings.model_copy(update=updates)


def render_startup_status(settings: Settings) -> str:
    guest_mode = "enabled" if settings.guest_mode_enabled else "disabled"
    admin_only = "enabled" if settings.guest_mode_admin_only else "disabled"
    business_mode = "enabled" if settings.business_mode_enabled else "disabled"
    business_reply = "enabled" if settings.business_reply_enabled else "disabled"
    streaming = "enabled" if settings.streaming_enabled else "disabled"
    private_draft = "enabled" if settings.streaming_private_draft_enabled else "disabled"
    group_fallback = "enabled" if settings.streaming_group_fallback_enabled else "disabled"
    raw_fallback = "enabled" if settings.streaming_draft_raw_api_fallback else "disabled"
    admin_count = len(settings.admin_ids)
    return "\n".join(
        [
            "polling started",
            f"allowed_updates: {', '.join(ALLOWED_UPDATES)}",
            f"guest mode: {guest_mode}",
            f"admin-only: {admin_only}",
            f"business mode: {business_mode}",
            f"business reply: {business_reply}",
            f"admin ids: SET count={admin_count}" if admin_count else "admin ids: MISSING",
            f"streaming: {streaming}",
            f"private draft streaming: {private_draft}",
            f"group fallback streaming: {group_fallback}",
            f"draft raw api fallback: {raw_fallback}",
            f"draft update interval ms: {settings.streaming_draft_update_interval_ms}",
            f"group edit interval ms: {settings.streaming_group_edit_interval_ms}",
            f"min chars delta: {settings.streaming_min_chars_delta}",
            f"max draft seconds: {settings.streaming_max_draft_seconds}",
            (
                "chat action interval seconds: "
                f"{settings.streaming_send_chat_action_interval_seconds}"
            ),
        ]
    )


def ensure_not_production_webhook_runtime(settings: Settings) -> None:
    if settings.app_env.lower() == "production":
        raise RuntimeError(PRODUCTION_POLLING_ERROR)


async def run_polling(
    *,
    settings: Settings,
    bot: PollingBot,
    dispatcher: PollingDispatcher,
    drop_pending_updates: bool,
    redis_pool: Any | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> None:
    ensure_not_production_webhook_runtime(settings)
    print(render_startup_status(settings))  # noqa: T201
    await bot.delete_webhook(drop_pending_updates=drop_pending_updates)
    engine = None
    is_real_dispatcher = isinstance(dispatcher, Dispatcher)
    owns_redis = redis_pool is None
    if session_factory is None and is_real_dispatcher:
        engine = make_engine(settings)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
    if is_real_dispatcher and session_factory is not None:
        dispatcher.update.middleware(PollingDatabaseSessionMiddleware(session_factory))
    if redis_pool is None and is_real_dispatcher:
        redis_pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    try:
        await dispatcher.start_polling(
            bot,
            allowed_updates=ALLOWED_UPDATES,
            settings=settings,
            redis=redis_pool,
            db_session=session_factory,
        )
    finally:
        if owns_redis and redis_pool is not None:
            await redis_pool.aclose()
        if engine is not None:
            await engine.dispose()
        close = getattr(bot.session, "close", None)
        if close is not None:
            await close()


async def async_main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    settings = resolve_host_polling_settings(Settings())
    try:
        ensure_not_production_webhook_runtime(settings)
    except RuntimeError as exc:
        print(str(exc))  # noqa: T201
        return 2
    if not settings.telegram_bot_token:
        print("Telegram token is not configured.")  # noqa: T201
        return 2
    bot = Bot(token=settings.telegram_bot_token)
    dispatcher: Dispatcher = build_dispatcher(settings)
    await run_polling(
        settings=settings,
        bot=bot,
        dispatcher=dispatcher,
        drop_pending_updates=bool(args.drop_pending_updates),
    )
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    return asyncio.run(async_main())


if __name__ == "__main__":
    sys.exit(main())
