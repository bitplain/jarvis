from typing import Annotated, Any

from aiogram import Bot
from aiogram.types import Update
from arq import create_pool
from arq.connections import RedisSettings
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.dispatcher import build_dispatcher
from app.bot.routers.business import BUSINESS_UPDATE_KEYS
from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.services.business_service import BusinessService

router = APIRouter(prefix="/telegram")


def verify_webhook_secret(settings: Settings, secret: str | None) -> None:
    if settings.telegram_webhook_secret and secret != settings.telegram_webhook_secret:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


@router.post("/webhook")
async def telegram_webhook(
    request: Request,
    payload: dict[str, Any],
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[AsyncSession, Depends(get_session)],
    x_telegram_bot_api_secret_token: Annotated[str | None, Header()] = None,
) -> dict[str, str]:
    verify_webhook_secret(settings, x_telegram_bot_api_secret_token)
    if not settings.telegram_bot_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telegram token is not configured",
        )
    for key in BUSINESS_UPDATE_KEYS:
        if key in payload:
            await BusinessService().record_business_event(key, payload)
            return {"status": "accepted"}
    bot = getattr(request.app.state, "bot", None) or Bot(token=settings.telegram_bot_token)
    dispatcher = getattr(request.app.state, "dispatcher", None)
    if dispatcher is None:
        dispatcher = build_dispatcher(settings)
        request.app.state.dispatcher = dispatcher
    redis = getattr(request.app.state, "redis_pool", None)
    if redis is None:
        redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    update = Update.model_validate(payload, context={"bot": bot})
    await dispatcher.feed_update(bot, update, db_session=session, redis=redis, settings=settings)
    return {"status": "accepted"}
