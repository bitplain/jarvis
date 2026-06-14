from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx


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


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in raw_line:
            continue
        key, raw_value = raw_line.split("=", 1)
        value = raw_value.strip()
        if " #" in value:
            value = value.split(" #", 1)[0].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def _sanitize_error(value: str) -> str:
    sanitized = re.sub(r"bot\d+:[A-Za-z0-9_-]+", "bot<redacted>", value)
    sanitized = re.sub(r"Bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer <redacted>", sanitized)
    return sanitized[:240]


def _webhook_url(public_base_url: str) -> str:
    return f"{public_base_url.rstrip('/')}/telegram/webhook"


def _public_https(public_base_url: str) -> bool:
    parsed = urlparse(public_base_url)
    return parsed.scheme == "https" and parsed.hostname not in {None, "", "localhost", "127.0.0.1"}


def _safe_url_fields(url: str) -> dict[str, str]:
    parsed = urlparse(url)
    return {
        "webhook_host": parsed.hostname or "<missing>",
        "webhook_path": parsed.path or "/",
    }


def set_webhook(
    env_path: Path = Path(".env"),
    *,
    http: TelegramHttp | None = None,
) -> WebhookResult:
    env = parse_env_file(env_path)
    token = env.get("TELEGRAM_BOT_TOKEN", "")
    secret = env.get("TELEGRAM_WEBHOOK_SECRET", "")
    public_base_url = env.get("PUBLIC_BASE_URL", "")
    if not token:
        return WebhookResult(action="set", ok=False, error="TELEGRAM_BOT_TOKEN missing")
    if not secret:
        return WebhookResult(action="set", ok=False, error="TELEGRAM_WEBHOOK_SECRET missing")
    if not _public_https(public_base_url):
        return WebhookResult(action="set", ok=False, error="PUBLIC_BASE_URL is not public HTTPS")
    url = _webhook_url(public_base_url)
    client = http or httpx.Client()
    try:
        response = client.post(
            f"https://api.telegram.org/bot{token}/setWebhook",
            json={"url": url, "secret_token": secret},
            timeout=30.0,
        )
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        return WebhookResult(action="set", ok=False, error=_sanitize_error(type(exc).__name__))
    ok = response.status_code < 400 and payload.get("ok") is True
    error = "" if ok else _sanitize_error(str(payload.get("description") or payload))
    return WebhookResult(action="set", ok=ok, fields=_safe_url_fields(url), error=error)


def get_webhook_info(
    env_path: Path = Path(".env"),
    *,
    http: TelegramHttp | None = None,
) -> WebhookResult:
    env = parse_env_file(env_path)
    token = env.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        return WebhookResult(action="info", ok=False, error="TELEGRAM_BOT_TOKEN missing")
    client = http or httpx.Client()
    try:
        response = client.get(f"https://api.telegram.org/bot{token}/getWebhookInfo", timeout=30.0)
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        return WebhookResult(action="info", ok=False, error=_sanitize_error(type(exc).__name__))
    result = payload.get("result") if isinstance(payload, dict) else {}
    fields: dict[str, str] = {}
    if isinstance(result, dict):
        url = str(result.get("url") or "")
        if url:
            fields.update(_safe_url_fields(url))
        fields["pending_update_count"] = str(result.get("pending_update_count", 0))
        last_error = result.get("last_error_message")
        if isinstance(last_error, str) and last_error:
            fields["last_error"] = _sanitize_error(last_error)
    ok = response.status_code < 400 and payload.get("ok") is True
    error = "" if ok else _sanitize_error(str(payload.get("description") or payload))
    return WebhookResult(action="info", ok=ok, fields=fields, error=error)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Set or inspect Telegram webhook safely.")
    parser.add_argument("--info", action="store_true", help="Show sanitized getWebhookInfo result.")
    parser.add_argument("--env-file", default=".env", help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    env_path = Path(args.env_file)
    result = get_webhook_info(env_path) if args.info else set_webhook(env_path)
    print(result.render_sanitized())  # noqa: T201
    return 0 if result.ok else 2


if __name__ == "__main__":
    sys.exit(main())
