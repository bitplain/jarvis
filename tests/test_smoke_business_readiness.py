import importlib.util
import sys
from pathlib import Path

import pytest

from app.core.config import Settings


def load_readiness_module():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "smoke_business_readiness.py"
    spec = importlib.util.spec_from_file_location("smoke_business_readiness", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["smoke_business_readiness"] = module
    spec.loader.exec_module(module)
    return module


class FakeBot:
    def __init__(self) -> None:
        self.get_me_called = False
        self.closed = False

    async def get_me(self) -> object:
        self.get_me_called = True
        return object()

    @property
    def session(self) -> "FakeBot":
        return self

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_business_readiness_checks_sanitized_dependencies_without_getupdates() -> None:
    module = load_readiness_module()
    bot = FakeBot()

    result = await module.run_readiness(
        settings=Settings(
            telegram_bot_token="123456:secret-token",
            admin_telegram_ids="100500",
            business_mode_enabled=True,
            business_reply_enabled=True,
            business_admin_only=True,
            yandex_ai_model="model",
            openrouter_model="model",
        ),
        bot=bot,
        postgres_probe=lambda: True,
        redis_probe=lambda: True,
        llm_smoke=lambda: "PASS_LLM_SMOKE",
    )

    rendered = result.render_sanitized()
    assert bot.get_me_called is True
    assert bot.closed is True
    assert result.verdict == "PASS_BUSINESS_READINESS"
    assert "business_connection" in rendered
    assert "business_message" in rendered
    assert "getUpdates" not in rendered
    assert "100500" not in rendered
    assert "secret-token" not in rendered


def test_business_readiness_reports_missing_reply_flag_as_blocked() -> None:
    module = load_readiness_module()
    result = module.BusinessReadinessResult(
        statuses={
            "business_mode_enabled": "true",
            "business_reply_enabled": "false",
            "allowed_updates": "OK business_connection,business_message",
        },
        verdict="BLOCKED_BUSINESS_READINESS",
    )

    rendered = result.render_sanitized()

    assert "business_reply_enabled: false" in rendered
    assert "BLOCKED_BUSINESS_READINESS" in rendered
