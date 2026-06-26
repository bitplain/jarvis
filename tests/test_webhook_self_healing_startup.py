from pathlib import Path

import pytest

from app.core.config import Settings
from app.main import create_app
from app.services.telegram_webhook_setup import WebhookResult, set_webhook_from_values


class FakeTelegramFailureResponse:
    status_code = 400

    def json(self) -> dict[str, object]:
        return {
            "ok": False,
            "description": (
                "Bad Request: https://api.telegram.org/bot123456:abcdefghijklmnopqrstuvwxyz/"
                "setWebhook Authorization: Bearer secret-value"
            ),
        }


class FakeTelegramFailureHttp:
    def post(
        self,
        url: str,
        *,
        json: dict[str, object] | None = None,
        timeout: float | None = None,
    ) -> FakeTelegramFailureResponse:
        del url, json, timeout
        return FakeTelegramFailureResponse()

    def get(self, url: str, *, timeout: float | None = None) -> FakeTelegramFailureResponse:
        del url, timeout
        return FakeTelegramFailureResponse()


@pytest.mark.asyncio
async def test_production_api_startup_runs_webhook_setup_after_migrations() -> None:
    calls: list[str] = []

    async def fake_migrations() -> None:
        calls.append("migrations")

    async def fake_webhook_setup(settings: Settings) -> None:
        assert settings.app_env == "production"
        calls.append("webhook")

    app = create_app(
        settings=Settings(_env_file=None, app_env="production"),
        startup_migration_runner=fake_migrations,
        startup_webhook_runner=fake_webhook_setup,
    )

    async with app.router.lifespan_context(app):
        pass

    assert calls == ["migrations", "webhook"]


@pytest.mark.asyncio
async def test_non_production_startup_does_not_run_webhook_setup() -> None:
    calls: list[str] = []

    async def fake_webhook_setup(settings: Settings) -> None:
        del settings
        calls.append("webhook")

    app = create_app(
        settings=Settings(_env_file=None, app_env="local"),
        startup_webhook_runner=fake_webhook_setup,
    )

    async with app.router.lifespan_context(app):
        pass

    assert calls == []


@pytest.mark.asyncio
async def test_missing_webhook_token_does_not_fail_production_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records: list[tuple[str, dict[str, object]]] = []

    def capture_log(message: str, *args: object, **kwargs: object) -> None:
        del args
        records.append((message, dict(kwargs.get("extra", {}))))

    monkeypatch.setattr("app.services.telegram_webhook_setup.logger.info", capture_log)
    monkeypatch.setattr("app.services.telegram_webhook_setup.logger.warning", capture_log)
    app = create_app(
        settings=Settings(
            _env_file=None,
            app_env="production",
            telegram_bot_token="",
            telegram_webhook_secret="secret",
            public_base_url="https://jarvis.example.com",
            startup_migrations_enabled=False,
        )
    )

    async with app.router.lifespan_context(app):
        pass

    assert records == [
        (
            "telegram_webhook_setup_started",
            {"webhook_host": "jarvis.example.com", "webhook_path": "/telegram/webhook"},
        ),
        (
            "telegram_webhook_setup_failed",
            {
                "webhook_host": "jarvis.example.com",
                "webhook_path": "/telegram/webhook",
                "error": "TELEGRAM_BOT_TOKEN missing",
            },
        ),
    ]


@pytest.mark.asyncio
async def test_webhook_setup_failure_does_not_fail_production_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records: list[tuple[str, dict[str, object]]] = []

    def capture_warning(message: str, *args: object, **kwargs: object) -> None:
        del args
        records.append((message, dict(kwargs.get("extra", {}))))

    monkeypatch.setattr("app.main.logger.warning", capture_warning)

    async def failing_webhook_setup(settings: Settings) -> None:
        del settings
        raise RuntimeError("temporary telegram outage")

    app = create_app(
        settings=Settings(
            _env_file=None,
            app_env="production",
            startup_migrations_enabled=False,
        ),
        startup_webhook_runner=failing_webhook_setup,
    )

    async with app.router.lifespan_context(app):
        pass

    assert records == [
        ("telegram_webhook_setup_failed", {"error_type": "RuntimeError"}),
    ]


@pytest.mark.asyncio
async def test_webhook_setup_logs_do_not_contain_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "fake-token-value-with-secret-fragment"
    records: list[tuple[str, dict[str, object]]] = []

    def capture_log(message: str, *args: object, **kwargs: object) -> None:
        del args
        records.append((message, dict(kwargs.get("extra", {}))))

    def fake_set_webhook_from_values(
        values: object,
    ) -> WebhookResult:
        del values
        return WebhookResult(
            action="set",
            ok=True,
            fields={"webhook_host": "jarvis.example.com", "webhook_path": "/telegram/webhook"},
        )

    monkeypatch.setattr(
        "app.services.telegram_webhook_setup.set_webhook_from_values",
        fake_set_webhook_from_values,
    )
    monkeypatch.setattr("app.services.telegram_webhook_setup.logger.info", capture_log)
    monkeypatch.setattr("app.services.telegram_webhook_setup.logger.warning", capture_log)
    app = create_app(
        settings=Settings(
            _env_file=None,
            app_env="production",
            telegram_bot_token=token,
            telegram_webhook_secret="secret",
            public_base_url="https://jarvis.example.com",
            startup_migrations_enabled=False,
        )
    )

    async with app.router.lifespan_context(app):
        pass

    rendered_logs = repr(records)
    assert "telegram_webhook_setup" in rendered_logs
    assert token not in rendered_logs
    assert "secret-fragment" not in rendered_logs


def test_worker_startup_does_not_import_webhook_setup() -> None:
    worker_sources = [
        Path("app/workers/arq_settings.py").read_text(encoding="utf-8"),
        Path("app/workers/jobs.py").read_text(encoding="utf-8"),
    ]

    assert all("telegram_webhook_setup" not in source for source in worker_sources)
    assert all("set_webhook" not in source for source in worker_sources)


def test_webhook_setup_result_redacts_telegram_url_and_authorization() -> None:
    token = "123456:abcdefghijklmnopqrstuvwxyz"

    result = set_webhook_from_values(
        {
            "TELEGRAM_BOT_TOKEN": token,
            "TELEGRAM_WEBHOOK_SECRET": "secret",
            "PUBLIC_BASE_URL": "https://jarvis.example.com",
        },
        http=FakeTelegramFailureHttp(),
    )

    rendered = result.render_sanitized()
    assert token not in rendered
    assert "abcdefghijklmnopqrstuvwxyz" not in rendered
    assert "secret-value" not in rendered
    assert "https://api.telegram.org/bot<redacted>/setWebhook" in rendered
    assert "Authorization: <redacted>" in rendered
