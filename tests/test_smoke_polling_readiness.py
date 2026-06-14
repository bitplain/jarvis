import importlib.util
import sys
from pathlib import Path

import pytest

from app.core.config import Settings


def load_readiness_module():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "smoke_polling_readiness.py"
    spec = importlib.util.spec_from_file_location("smoke_polling_readiness", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["smoke_polling_readiness"] = module
    spec.loader.exec_module(module)
    return module


class FakeBot:
    def __init__(self) -> None:
        self.delete_webhook_calls: list[dict[str, object]] = []
        self.get_me_called = False
        self.closed = False

    async def delete_webhook(self, *, drop_pending_updates: bool) -> None:
        self.delete_webhook_calls.append({"drop_pending_updates": drop_pending_updates})

    async def get_me(self) -> object:
        self.get_me_called = True
        return object()

    @property
    def session(self) -> "FakeBot":
        return self

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_polling_readiness_deletes_webhook_without_getting_updates() -> None:
    module = load_readiness_module()
    bot = FakeBot()

    result = await module.run_readiness(
        settings=Settings(
            telegram_bot_token="123456:secret-token",
            admin_telegram_ids="100500",
            guest_mode_enabled=True,
            guest_mode_admin_only=True,
            yandex_ai_api_key="yandex-secret",
            yandex_ai_model="model",
            openrouter_api_key="openrouter-secret",
            openrouter_model="model",
        ),
        bot=bot,
        postgres_probe=lambda: True,
        redis_probe=lambda: True,
        llm_smoke=lambda: "PASS_LLM_SMOKE",
    )

    assert bot.delete_webhook_calls == [{"drop_pending_updates": False}]
    assert bot.get_me_called is True
    assert bot.closed is True
    assert result.verdict == "PASS_POLLING_READINESS"
    assert "getUpdates" not in result.render_sanitized()


def test_polling_readiness_sanitized_output_hides_secrets() -> None:
    module = load_readiness_module()
    result = module.PollingReadinessResult(
        statuses={
            "telegram_token": "SET",
            "admin_ids": "SET count=1",
            "openrouter": "SET",
        },
        verdict="PASS_POLLING_READINESS",
    )

    rendered = result.render_sanitized()

    assert "100500" not in rendered
    assert "secret" not in rendered.lower()
    assert "PASS_POLLING_READINESS" in rendered
