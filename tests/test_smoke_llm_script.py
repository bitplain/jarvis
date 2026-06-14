import importlib.util
import sys
from pathlib import Path

import pytest

from app.llm.base import LLMProviderError
from app.llm.types import LLMMessage, LLMResponse


def load_smoke_module():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "smoke_llm.py"
    spec = importlib.util.spec_from_file_location("smoke_llm", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["smoke_llm"] = module
    spec.loader.exec_module(module)
    return module


class WorkingProvider:
    def __init__(self, name: str) -> None:
        self.name = name
        self.model = f"{name}-model"

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        del max_tokens
        return LLMResponse(content="тест", provider=self.name, model=self.model)

    async def stream(self, messages: list[LLMMessage]):
        yield "тест"

    async def list_models(self) -> list[str]:
        return [self.model]


class FailingProvider(WorkingProvider):
    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        del max_tokens
        raise LLMProviderError("rate_limited", retryable=True)


@pytest.mark.asyncio
async def test_run_smoke_checks_yandex_openrouter_and_forced_fallback() -> None:
    module = load_smoke_module()

    result = await module.run_smoke(
        yandex=WorkingProvider("yandex"),
        openrouter=WorkingProvider("openrouter"),
        forced_primary=FailingProvider("forced-yandex"),
        forced_fallback=WorkingProvider("openrouter"),
    )

    rendered = result.render_sanitized()
    assert result.verdict == "PASS_LLM_SMOKE"
    assert "yandex: OK" in rendered
    assert "openrouter: OK" in rendered
    assert "forced_fallback: OK" in rendered
