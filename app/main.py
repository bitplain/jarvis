from collections.abc import Awaitable, Callable

import redis.asyncio as redis
from fastapi import FastAPI

from app.api import routes_admin, routes_health, routes_telegram
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import ping_postgres

ReadyProbe = Callable[[], Awaitable[dict[str, bool]]]


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


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(title="Jarvis Telegram AI Bot", version="0.1.0")
    app.state.default_ready_probe = default_ready_probe
    app.include_router(routes_health.router)
    app.include_router(routes_admin.router)
    app.include_router(routes_telegram.router)
    return app


app = create_app()
