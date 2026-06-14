import importlib.util
import sys
from pathlib import Path

import pytest

from app.core.config import Settings


def load_readiness_module():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "smoke_streaming_readiness.py"
    spec = importlib.util.spec_from_file_location("smoke_streaming_readiness", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["smoke_streaming_readiness"] = module
    spec.loader.exec_module(module)
    return module


class FakeBot:
    def __init__(self) -> None:
        self.closed = False

    async def get_me(self) -> object:
        return object()

    @property
    def session(self) -> "FakeBot":
        return self

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_streaming_readiness_passes_without_live_updates_or_secrets() -> None:
    module = load_readiness_module()
    bot = FakeBot()

    result = await module.run_readiness(
        settings=Settings(
            telegram_bot_token="123456:secret-token",
            admin_telegram_ids="100500",
            streaming_enabled=True,
            streaming_private_draft_enabled=True,
            streaming_group_fallback_enabled=True,
            streaming_draft_raw_api_fallback=True,
            yandex_ai_model="model",
            openrouter_model="model",
        ),
        bot=bot,
        llm_probe=lambda: "PASS_LLM_SMOKE",
        polling_probe=lambda: "PASS_POLLING_READINESS",
        group_probe=lambda: "PASS_GROUP_READINESS",
    )

    rendered = result.render_sanitized()
    assert result.verdict == "PASS_STREAMING_READINESS"
    assert "streaming_enabled: true" in rendered
    assert "draft_adapter_import: OK" in rendered
    assert "buffer_config: OK" in rendered
    assert "worker_import: OK" in rendered
    assert "secret-token" not in rendered
    assert "100500" not in rendered
    assert bot.closed is True
