import io
import logging
import sys

import httpx
import pytest

from app.core.logging import configure_logging, redact, safe_extra


def test_redact_masks_telegram_bot_api_url() -> None:
    token = "123456:abcdefghijklmnopqrstuvwxyz"
    raw = f"https://api.telegram.org/bot{token}/setWebhook"

    rendered = str(redact(f"HTTP Request: POST {raw}"))

    assert token not in rendered
    assert "abcdefghijklmnopqrstuvwxyz" not in rendered
    assert "https://api.telegram.org/bot<redacted>/setWebhook" in rendered


def test_redact_masks_httpx_url_object() -> None:
    token = "123456:abcdefghijklmnopqrstuvwxyz"
    raw = httpx.URL(f"https://api.telegram.org/bot{token}/getWebhookInfo")

    rendered = str(redact(raw))

    assert token not in rendered
    assert rendered == "https://api.telegram.org/bot<redacted>/getWebhookInfo"


def test_redact_masks_authorization_header_forms() -> None:
    rendered = str(
        redact(
            {
                "Authorization": "Bearer real-secret-token",
                "message": "Authorization: Bearer another-secret-token",
                "nested": ["api_key=secret-value"],
            }
        )
    )

    assert "real-secret-token" not in rendered
    assert "another-secret-token" not in rendered
    assert "secret-value" not in rendered
    assert "Authorization: <redacted>" in rendered


def test_safe_extra_redacts_secret_values_before_logging() -> None:
    token = "123456:abcdefghijklmnopqrstuvwxyz"

    extra = safe_extra(
        url=f"https://api.telegram.org/bot{token}/setWebhook",
        headers={"Authorization": "Bearer secret-value"},
        plain="ok",
    )["extra"]

    rendered = repr(extra)
    assert token not in rendered
    assert "secret-value" not in rendered
    assert extra["plain"] == "ok"


def test_configure_logging_routes_info_to_stdout_and_errors_to_stderr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)

    configure_logging("INFO")
    logger = logging.getLogger("tests.logging_hygiene")
    logger.info("normal_operational_event")
    logger.error("real_error_event")

    assert "normal_operational_event" in stdout.getvalue()
    assert "normal_operational_event" not in stderr.getvalue()
    assert "real_error_event" in stderr.getvalue()


def test_redacting_filter_preserves_named_logging_args(monkeypatch: pytest.MonkeyPatch) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)
    configure_logging("INFO")

    token = "123456:abcdefghijklmnopqrstuvwxyz"
    logging.getLogger("tests.logging_hygiene").info(
        "telegram_url=%(url)s",
        {"url": f"https://api.telegram.org/bot{token}/setWebhook"},
    )

    rendered = stdout.getvalue()
    assert token not in rendered
    assert "telegram_url=https://api.telegram.org/bot<redacted>/setWebhook" in rendered
    assert stderr.getvalue() == ""


def test_configure_logging_quiets_http_client_info_logs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    monkeypatch.setattr(sys, "stderr", io.StringIO())

    configure_logging("INFO")

    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
    assert logging.getLogger("httpcore").getEffectiveLevel() >= logging.WARNING
    assert logging.getLogger("aiohttp").getEffectiveLevel() >= logging.WARNING
