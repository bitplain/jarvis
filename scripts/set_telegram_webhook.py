from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from app.services.telegram_webhook_setup import (
    TelegramHttp,
    WebhookResult,
    get_webhook_info_from_values,
    set_webhook_from_values,
)


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


def load_env_values(path: Path) -> dict[str, str]:
    values = dict(os.environ)
    values.update(parse_env_file(path))
    return values


def set_webhook(
    env_path: Path = Path(".env"),
    *,
    http: TelegramHttp | None = None,
) -> WebhookResult:
    return set_webhook_from_values(load_env_values(env_path), http=http)


def get_webhook_info(
    env_path: Path = Path(".env"),
    *,
    http: TelegramHttp | None = None,
) -> WebhookResult:
    return get_webhook_info_from_values(load_env_values(env_path), http=http)


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
