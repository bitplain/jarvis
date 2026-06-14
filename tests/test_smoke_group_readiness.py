import importlib.util
import sys
from pathlib import Path

import pytest

from app.core.config import Settings


def load_group_readiness_module():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "smoke_group_readiness.py"
    spec = importlib.util.spec_from_file_location("smoke_group_readiness", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["smoke_group_readiness"] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_group_readiness_checks_routing_without_getupdates() -> None:
    module = load_group_readiness_module()

    result = await module.run_readiness(
        settings=Settings(
            telegram_bot_token="123456:secret-token",
            telegram_bot_username="jarvis_bot",
            admin_telegram_ids="100500",
            group_assistant_enabled=True,
            yandex_ai_model="model",
            openrouter_model="model",
        ),
        polling_readiness=lambda: "PASS_POLLING_READINESS",
        llm_smoke=lambda: "PASS_LLM_SMOKE",
    )

    rendered = result.render_sanitized()
    assert result.verdict == "PASS_GROUP_READINESS"
    assert "telegram_token: SET" in rendered
    assert "telegram_username: SET" in rendered
    assert "admin_ids: SET count=1" in rendered
    assert "allowed_updates_message: OK" in rendered
    assert "group_router_registered: OK" in rendered
    assert "private_router_filter: OK" in rendered
    assert "group_router_filter: OK" in rendered
    assert "group_plain_ignore_test: OK" in rendered
    assert "group_mention_reply_test: OK" in rendered
    assert "secret-token" not in rendered
    assert "100500" not in rendered
