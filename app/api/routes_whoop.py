from __future__ import annotations

import inspect
import secrets
from datetime import UTC, datetime
from typing import Annotated, Any

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.core.config import Settings, get_settings
from app.db.repositories.whoop import WhoopIntegrationRepository
from app.db.session import SessionLocal
from app.services.secret_cipher import SecretCipher, SecretCipherUnavailable
from app.services.whoop_client import build_authorization_url, exchange_code_for_tokens, get_profile
from app.services.whoop_sync import expires_at_from_token

router = APIRouter()
WHOOP_OAUTH_STATE_TTL_SECONDS = 600
WHOOP_OAUTH_START_TTL_SECONDS = 600
WHOOP_OAUTH_START_PREFIX = "whoop:oauth:start:"
WHOOP_OAUTH_STATE_PREFIX = "whoop:oauth:state:"


@router.get("/integrations/whoop/oauth/start", response_model=None)
async def whoop_oauth_start(
    request: Request,
    connect_token: str,
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    if not settings.whoop_configured:
        return _error_page("WHOOP не настроен.", status.HTTP_503_SERVICE_UNAVAILABLE)
    redis = await _get_redis_pool(request, settings)
    telegram_user_id = await _consume_redis_value(
        redis,
        f"{WHOOP_OAUTH_START_PREFIX}{connect_token}",
    )
    if telegram_user_id is None:
        return _error_page("Ссылка WHOOP устарела. Вернитесь в Telegram и откройте новую.")
    state = secrets.token_urlsafe(32)
    await redis.set(
        f"{WHOOP_OAUTH_STATE_PREFIX}{state}",
        telegram_user_id,
        ex=WHOOP_OAUTH_STATE_TTL_SECONDS,
        nx=True,
    )
    authorization_url = build_authorization_url(
        client_id=settings.whoop_client_id,
        redirect_uri=settings.whoop_redirect_uri,
        state=state,
    )
    return RedirectResponse(authorization_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@router.get("/integrations/whoop/oauth/callback")
async def whoop_oauth_callback(
    request: Request,
    state: str,
    code: str,
    settings: Annotated[Settings, Depends(get_settings)],
) -> HTMLResponse:
    if not settings.whoop_configured:
        return _error_page("WHOOP не настроен.", status.HTTP_503_SERVICE_UNAVAILABLE)
    redis = await _get_redis_pool(request, settings)
    telegram_user_id = await _consume_redis_value(redis, f"{WHOOP_OAUTH_STATE_PREFIX}{state}")
    if telegram_user_id is None:
        return _error_page("OAuth state устарел или неверен.")
    connector = getattr(request.app.state, "whoop_oauth_connector", None)
    try:
        if connector is not None:
            complete = getattr(connector, "complete", connector)
            result = complete(
                telegram_user_id=int(telegram_user_id),
                code=code,
                settings=settings,
            )
            if inspect.isawaitable(result):
                await result
        else:
            await complete_whoop_oauth_connection(
                telegram_user_id=int(telegram_user_id),
                code=code,
                settings=settings,
            )
    except SecretCipherUnavailable:
        return _error_page("WHOOP token storage не настроен.", status.HTTP_503_SERVICE_UNAVAILABLE)
    except Exception:
        return _error_page("Не удалось подключить WHOOP. Попробуйте позже.")
    return HTMLResponse(
        "<html><body><h1>WHOOP подключён</h1>"
        "<p>Можно закрыть окно и вернуться в Telegram.</p></body></html>"
    )


async def complete_whoop_oauth_connection(
    *,
    telegram_user_id: int,
    code: str,
    settings: Settings,
) -> None:
    cipher = SecretCipher(settings.whoop_token_encryption_key)
    token_set = await exchange_code_for_tokens(code=code, settings=settings)
    profile = await get_profile(access_token=token_set.access_token)
    async with SessionLocal() as session:
        await WhoopIntegrationRepository(session).upsert_connected_integration(
            telegram_user_id=telegram_user_id,
            scope=token_set.scope,
            access_token_encrypted=cipher.encrypt(token_set.access_token),
            refresh_token_encrypted=cipher.encrypt(token_set.refresh_token),
            expires_at=expires_at_from_token(token_set, now=datetime.now(UTC)),
            whoop_user_id=_optional_int(profile.get("user_id")),
            profile_json=profile,
        )


async def store_whoop_connect_token(redis: Any, *, token: str, telegram_user_id: int) -> None:
    await redis.set(
        f"{WHOOP_OAUTH_START_PREFIX}{token}",
        str(telegram_user_id),
        ex=WHOOP_OAUTH_START_TTL_SECONDS,
        nx=True,
    )


async def _get_redis_pool(request: Request, settings: Settings) -> Any:
    redis = getattr(request.app.state, "redis_pool", None)
    if redis is not None:
        return redis
    redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    request.app.state.redis_pool = redis
    return redis


async def _consume_redis_value(redis: Any, key: str) -> str | None:
    raw = await redis.get(key)
    if raw is None:
        return None
    await redis.delete(key)
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="ignore")
    return str(raw)


def _error_page(message: str, status_code: int = status.HTTP_400_BAD_REQUEST) -> HTMLResponse:
    return HTMLResponse(
        f"<html><body><h1>WHOOP</h1><p>{message}</p></body></html>",
        status_code=status_code,
    )


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return int(str(value))
