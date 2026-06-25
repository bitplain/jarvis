from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import FastAPI

from app.api import routes_admin, routes_health, routes_telegram
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.db.session import ping_postgres
from app.services.startup_migrations import run_startup_migrations, should_run_startup_migrations

ReadyProbe = Callable[[], Awaitable[dict[str, bool]]]
StartupMigrationRunner = Callable[[], Awaitable[None]]


async def default_ready_probe() -> dict[str, bool]:
    settings = get_settings()
    postgres_ok = await ping_postgres()
    redis_ok = False
    try:
        client = redis.from_url(settings.redis_url)  # type: ignore[no-untyped-call]
        redis_ok = bool(await client.ping())
        await client.aclose()
    except Exception:
        redis_ok = False
    return {"postgres": postgres_ok, "redis": redis_ok}


async def default_startup_migration_runner() -> None:
    run_startup_migrations()


def create_app(
    *,
    settings: Settings | None = None,
    startup_migration_runner: StartupMigrationRunner | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if should_run_startup_migrations(resolved_settings):
            await app.state.startup_migration_runner()
        yield

    app = FastAPI(title="Jarvis Telegram AI Bot", version="0.1.0", lifespan=lifespan)
    app.state.default_ready_probe = default_ready_probe
    app.state.startup_migration_runner = (
        startup_migration_runner or default_startup_migration_runner
    )
    app.include_router(routes_health.router)
    app.include_router(routes_admin.router)
    app.include_router(routes_telegram.router)
    return app


app = create_app()
