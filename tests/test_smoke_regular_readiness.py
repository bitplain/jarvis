import importlib.util
import sys
from pathlib import Path

import pytest

from app.core.config import Settings


def load_readiness_module():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "smoke_regular_readiness.py"
    spec = importlib.util.spec_from_file_location("smoke_regular_readiness", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["smoke_regular_readiness"] = module
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
async def test_regular_readiness_does_not_require_business_account() -> None:
    module = load_readiness_module()
    bot = FakeBot()

    result = await module.run_readiness(
        settings=Settings(
            telegram_bot_token="123456:secret-token",
            admin_telegram_ids="100500",
            regular_assistant_enabled=True,
            forwarded_message_assistant_enabled=True,
            draft_reply_enabled=True,
            group_assistant_enabled=True,
            business_mode_enabled=False,
            business_reply_enabled=False,
            yandex_ai_model="model",
            openrouter_model="model",
        ),
        bot=bot,
        postgres_probe=lambda: True,
        redis_probe=lambda: True,
        llm_smoke=lambda: "PASS_LLM_SMOKE",
    )

    rendered = result.render_sanitized()
    assert result.verdict == "PASS_REGULAR_READINESS"
    assert bot.get_me_called is True
    assert bot.closed is True
    assert "business_mode_optional: OK disabled" in rendered
    assert "secret-token" not in rendered
    assert "100500" not in rendered
