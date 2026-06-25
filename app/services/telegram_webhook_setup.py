from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

from app.core.config import Settings

logger = logging.getLogger(__name__)


class JsonResponse(Protocol):
    status_code: int

    def json(self) -> dict[str, Any]:
        ...


class TelegramHttp(Protocol):
    def post(
        self,
        url: str,
        *,
        json: dict[str, object] | None = None,
        timeout: float | None = None,
    ) -> JsonResponse:
        ...

    def get(self, url: str, *, timeout: float | None = None) -> JsonResponse:
        ...


@dataclass
class WebhookResult:
    action: str
    ok: bool
    fields: dict[str, str] = field(default_factory=dict)
    error: str = ""

    def render_sanitized(self) -> str:
        lines = [f"telegram_webhook_{self.action}: {'ok' if self.ok else 'failed'}"]
        for key in sorted(self.fields):
            lines.append(f"{key}: {self.fields[key]}")
        if self.error:
            lines.append(f"error: {self.error}")
        return "\n".join(lines)


def sanitize_webhook_error(value: str) -> str:
    sanitized = re.sub(r"bot\d+:[A-Za-z0-9_-]+", "bot<redacted>", value)
    sanitized = re.sub(r"Bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer <redacted>", sanitized)
    return sanitized[:240]


def webhook_url(public_base_url: str) -> str:
    return f"{public_base_url.rstrip('/')}/telegram/webhook"


def public_https(public_base_url: str) -> bool:
    parsed = urlparse(public_base_url)
    return parsed.scheme == "https" and parsed.hostname not in {None, "", "localhost", "127.0.0.1"}


def safe_url_fields(url: str) -> dict[str, str]:
    parsed = urlparse(url)
    return {
        "webhook_host": parsed.hostname or "<missing>",
        "webhook_path": parsed.path or "/",
    }


def safe_settings_url_fields(settings: Settings) -> dict[str, str]:
    if not settings.public_base_url:
        return {"webhook_host": "<missing>", "webhook_path": "<missing>"}
    return safe_url_fields(webhook_url(settings.public_base_url))


def set_webhook_from_values(
    values: Mapping[str, str],
    *,
    http: TelegramHttp | None = None,
) -> WebhookResult:
    token = values.get("TELEGRAM_BOT_TOKEN", "")
    secret = values.get("TELEGRAM_WEBHOOK_SECRET", "")
    public_base_url = values.get("PUBLIC_BASE_URL", "")
    fields = (
        safe_url_fields(webhook_url(public_base_url))
        if public_base_url
        else {"webhook_host": "<missing>", "webhook_path": "<missing>"}
    )
    if not token:
        return WebhookResult(
            action="set",
            ok=False,
            fields=fields,
            error="TELEGRAM_BOT_TOKEN missing",
        )
    if not secret:
        return WebhookResult(
            action="set",
            ok=False,
            fields=fields,
            error="TELEGRAM_WEBHOOK_SECRET missing",
        )
    if not public_https(public_base_url):
        return WebhookResult(
            action="set",
            ok=False,
            fields=fields,
            error="PUBLIC_BASE_URL is not public HTTPS",
        )
    url = webhook_url(public_base_url)
    client = http or httpx.Client()
    try:
        response = client.post(
            f"https://api.telegram.org/bot{token}/setWebhook",
            json={"url": url, "secret_token": secret},
            timeout=30.0,
        )
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        return WebhookResult(
            action="set",
            ok=False,
            fields=fields,
            error=sanitize_webhook_error(type(exc).__name__),
        )
    ok = response.status_code < 400 and payload.get("ok") is True
    error = "" if ok else sanitize_webhook_error(str(payload.get("description") or payload))
    return WebhookResult(action="set", ok=ok, fields=fields, error=error)


def get_webhook_info_from_values(
    values: Mapping[str, str],
    *,
    http: TelegramHttp | None = None,
) -> WebhookResult:
    token = values.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        return WebhookResult(action="info", ok=False, error="TELEGRAM_BOT_TOKEN missing")
    client = http or httpx.Client()
    try:
        response = client.get(f"https://api.telegram.org/bot{token}/getWebhookInfo", timeout=30.0)
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        return WebhookResult(
            action="info",
            ok=False,
            error=sanitize_webhook_error(type(exc).__name__),
        )
    result = payload.get("result") if isinstance(payload, dict) else {}
    fields: dict[str, str] = {}
    if isinstance(result, dict):
        url = str(result.get("url") or "")
        if url:
            fields.update(safe_url_fields(url))
        fields["pending_update_count"] = str(result.get("pending_update_count", 0))
        last_error = result.get("last_error_message")
        if isinstance(last_error, str) and last_error:
            fields["last_error"] = sanitize_webhook_error(last_error)
    ok = response.status_code < 400 and payload.get("ok") is True
    error = "" if ok else sanitize_webhook_error(str(payload.get("description") or payload))
    return WebhookResult(action="info", ok=ok, fields=fields, error=error)


def should_run_startup_webhook_setup(settings: Settings) -> bool:
    return settings.app_env.lower() == "production"


def run_startup_webhook_setup(settings: Settings) -> None:
    fields = safe_settings_url_fields(settings)
    logger.info("telegram_webhook_setup_started", extra=fields)
    result = set_webhook_from_values(
        {
            "TELEGRAM_BOT_TOKEN": settings.telegram_bot_token,
            "TELEGRAM_WEBHOOK_SECRET": settings.telegram_webhook_secret,
            "PUBLIC_BASE_URL": settings.public_base_url,
        }
    )
    if result.ok:
        logger.info("telegram_webhook_setup_completed", extra=result.fields)
        return
    logger.warning(
        "telegram_webhook_setup_failed",
        extra={**result.fields, "error": result.error},
    )


async def run_startup_webhook_setup_async(settings: Settings) -> None:
    await asyncio.to_thread(run_startup_webhook_setup, settings)
