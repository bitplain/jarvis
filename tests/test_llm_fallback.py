import pytest

from app.llm.base import LLMProviderError
from app.llm.fallback import FallbackLLMProvider
from app.llm.types import LLMMessage, LLMResponse


class FailingProvider:
    name = "yandex"

    async def complete(self, messages: list[LLMMessage]) -> LLMResponse:
        raise LLMProviderError("rate_limited", retryable=True)

    async def stream(self, messages: list[LLMMessage]):
        raise LLMProviderError("rate_limited", retryable=True)

    async def list_models(self) -> list[str]:
        return []


class WorkingProvider:
    name = "openrouter"

    def __init__(self) -> None:
        self.called = False

    async def complete(self, messages: list[LLMMessage]) -> LLMResponse:
        self.called = True
        return LLMResponse(content="ответ", provider=self.name, model="model")

    async def stream(self, messages: list[LLMMessage]):
        yield "ответ"

    async def list_models(self) -> list[str]:
        return ["model"]


@pytest.mark.asyncio
async def test_fallback_provider_calls_openrouter_after_yandex_failure() -> None:
    fallback = WorkingProvider()
    provider = FallbackLLMProvider(primary=FailingProvider(), fallback=fallback)

    response = await provider.complete([LLMMessage(role="user", content="привет")])

    assert fallback.called is True
    assert response.provider == "openrouter"
