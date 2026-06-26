import logging
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
from app.core.logging import safe_extra
from app.db.session import get_session
from app.services.business_service import BusinessService

router = APIRouter(prefix="/telegram")
logger = logging.getLogger(__name__)
TELEGRAM_UPDATE_DEDUP_TTL_SECONDS = 600


def verify_webhook_secret(settings: Settings, secret: str | None) -> None:
    if settings.telegram_webhook_secret and secret != settings.telegram_webhook_secret:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


def _mask_int(value: int | None) -> str:
    if value is None:
        return "missing"
    text = str(value)
    prefix = "-" if text.startswith("-") else ""
    digits = text[1:] if prefix else text
    tail = digits[-4:] if len(digits) > 4 else digits
    return f"{prefix}***{tail}"


def _update_log_fields(payload: dict[str, Any]) -> dict[str, object]:
    message = payload.get("message")
    if not isinstance(message, dict):
        edited_message = payload.get("edited_message")
        message = edited_message if isinstance(edited_message, dict) else None
    callback_query = payload.get("callback_query")
    if message is None and isinstance(callback_query, dict):
        candidate = callback_query.get("message")
        message = candidate if isinstance(candidate, dict) else None
    chat = message.get("chat") if isinstance(message, dict) else None
    from_user = message.get("from") if isinstance(message, dict) else None
    if from_user is None and isinstance(callback_query, dict):
        from_user = callback_query.get("from")
    chat_type = chat.get("type") if isinstance(chat, dict) else None
    update_type = next((key for key in payload if key != "update_id"), "unknown")
    return {
        "update_id": payload.get("update_id"),
        "update_type": update_type,
        "message_id": message.get("message_id") if isinstance(message, dict) else None,
        "chat_type": chat_type or "unknown",
        "chat_id_masked": _mask_int(chat.get("id") if isinstance(chat, dict) else None),
        "user_id_masked": _mask_int(from_user.get("id") if isinstance(from_user, dict) else None),
        "private": chat_type == "private",
    }


async def _get_redis_pool(request: Request, settings: Settings) -> Any | None:
    redis = getattr(request.app.state, "redis_pool", None)
    if redis is not None:
        return redis
    try:
        redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    except Exception as exc:
        logger.warning(
            "telegram_webhook_redis_unavailable",
            extra={"error_type": type(exc).__name__},
        )
        redis = None
        return redis
    request.app.state.redis_pool = redis
    return redis


async def _claim_update_id(redis: Any | None, payload: dict[str, Any]) -> bool:
    update_id = payload.get("update_id")
    if not isinstance(update_id, int) or redis is None:
        return True
    key = f"telegram:update:{update_id}"
    try:
        claimed = await redis.set(key, "1", ex=TELEGRAM_UPDATE_DEDUP_TTL_SECONDS, nx=True)
    except Exception as exc:
        log_kwargs: dict[str, Any] = safe_extra(
            error_type=type(exc).__name__,
            **_update_log_fields(payload),
        )
        logger.warning(
            "telegram_webhook_dedup_unavailable",
            **log_kwargs,
        )
        return True
    if claimed:
        accepted_log_kwargs: dict[str, Any] = safe_extra(**_update_log_fields(payload))
        logger.info("telegram_webhook_update_accepted", **accepted_log_kwargs)
        return True
    duplicate_log_kwargs: dict[str, Any] = safe_extra(**_update_log_fields(payload))
    logger.info(
        "telegram_webhook_duplicate_update_skipped",
        **duplicate_log_kwargs,
    )
    return False


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
    redis = await _get_redis_pool(request, settings)
    if not await _claim_update_id(redis, payload):
        return {"status": "accepted"}
    for key in BUSINESS_UPDATE_KEYS:
        if key in payload:
            await BusinessService().record_business_event(key, payload)
            return {"status": "accepted"}
    bot = getattr(request.app.state, "bot", None) or Bot(token=settings.telegram_bot_token)
    dispatcher = getattr(request.app.state, "dispatcher", None)
    if dispatcher is None:
        dispatcher = build_dispatcher(settings)
        request.app.state.dispatcher = dispatcher
    update = Update.model_validate(payload, context={"bot": bot})
    await dispatcher.feed_update(bot, update, db_session=session, redis=redis, settings=settings)
    return {"status": "accepted"}
