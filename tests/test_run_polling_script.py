import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

from app.core.config import Settings


def load_run_polling_module():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "run_polling.py"
    spec = importlib.util.spec_from_file_location("run_polling", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_polling"] = module
    spec.loader.exec_module(module)
    return module


class FakeBot:
    def __init__(self) -> None:
        self.delete_webhook_calls: list[dict[str, object]] = []
        self.closed = False

    async def delete_webhook(self, *, drop_pending_updates: bool) -> None:
        self.delete_webhook_calls.append({"drop_pending_updates": drop_pending_updates})

    @property
    def session(self) -> "FakeBot":
        return self

    async def close(self) -> None:
        self.closed = True


class FakeDispatcher:
    def __init__(self) -> None:
        self.start_polling_calls: list[dict[str, Any]] = []

    async def start_polling(self, bot: FakeBot, **kwargs: Any) -> None:
        self.start_polling_calls.append({"bot": bot, **kwargs})


@pytest.mark.asyncio
async def test_polling_runner_deletes_webhook_before_polling_by_default() -> None:
    module = load_run_polling_module()
    bot = FakeBot()
    dispatcher = FakeDispatcher()
    settings = Settings(
        telegram_bot_token="123456:secret-token",
        admin_telegram_ids="100500",
        guest_mode_enabled=True,
        guest_mode_admin_only=True,
    )

    await module.run_polling(
        settings=settings,
        bot=bot,
        dispatcher=dispatcher,
        drop_pending_updates=False,
    )

    assert bot.delete_webhook_calls == [{"drop_pending_updates": False}]
    assert dispatcher.start_polling_calls[0]["allowed_updates"] == module.ALLOWED_UPDATES
    assert "guest_message" in module.ALLOWED_UPDATES
    assert module.ALLOWED_UPDATES[:4] == [
        "business_connection",
        "business_message",
        "edited_business_message",
        "deleted_business_messages",
    ]
    assert dispatcher.start_polling_calls[0]["settings"] is settings
    assert bot.closed is True


@pytest.mark.asyncio
async def test_polling_runner_supports_explicit_drop_pending_updates() -> None:
    module = load_run_polling_module()
    bot = FakeBot()
    dispatcher = FakeDispatcher()

    await module.run_polling(
        settings=Settings(telegram_bot_token="token", guest_mode_enabled=True),
        bot=bot,
        dispatcher=dispatcher,
        drop_pending_updates=True,
    )

    assert bot.delete_webhook_calls == [{"drop_pending_updates": True}]


def test_parse_args_keeps_pending_updates_by_default() -> None:
    module = load_run_polling_module()

    args = module.parse_args([])

    assert args.drop_pending_updates is False


def test_sanitized_startup_does_not_include_secrets() -> None:
    module = load_run_polling_module()
    settings = Settings(
        telegram_bot_token="123456:secret-token",
        admin_api_token="admin-secret",
        openrouter_api_key="openrouter-secret",
        yandex_ai_api_key="yandex-secret",
        admin_telegram_ids="100500",
        guest_mode_enabled=True,
        guest_mode_admin_only=True,
    )

    rendered = module.render_startup_status(settings)

    assert "secret-token" not in rendered
    assert "admin-secret" not in rendered
    assert "openrouter-secret" not in rendered
    assert "yandex-secret" not in rendered
    assert "100500" not in rendered
    assert "guest mode: enabled" in rendered
    assert "admin-only: enabled" in rendered
    assert "business mode: disabled" in rendered
    assert "business reply: disabled" in rendered
    assert "streaming: enabled" in rendered
    assert "private draft streaming: enabled" in rendered
    assert "group fallback streaming: enabled" in rendered
    assert "draft raw api fallback: enabled" in rendered
    assert "draft update interval ms: 800" in rendered
    assert "group edit interval ms: 1000" in rendered
    assert "min chars delta: 120" in rendered
    assert "max draft seconds: 25" in rendered
    assert "chat action interval seconds: 4" in rendered


def test_host_polling_settings_map_docker_hostnames_to_localhost() -> None:
    module = load_run_polling_module()

    settings = module.resolve_host_polling_settings(
        Settings(postgres_host="postgres", redis_url="redis://redis:6379/0")
    )

    assert settings.postgres_host == "localhost"
    assert settings.redis_url == "redis://localhost:6379/0"
