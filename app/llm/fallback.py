import logging
from collections.abc import AsyncIterator

from app.llm.base import LLMProvider, LLMProviderError
from app.llm.types import LLMMessage, LLMResponse, LLMStreamChunk

logger = logging.getLogger(__name__)


class FallbackLLMProvider(LLMProvider):
    name = "fallback"

    def __init__(self, *, primary: LLMProvider, fallback: LLMProvider) -> None:
        self.primary = primary
        self.fallback = fallback

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        try:
            return await self.primary.complete(messages, max_tokens=max_tokens)
        except LLMProviderError as exc:
            if not exc.retryable:
                raise
            logger.warning(
                "primary_llm_failed_trying_fallback",
                extra={"provider": self.primary.name, "error_code": exc.code},
            )
            return await self.fallback.complete(messages, max_tokens=max_tokens)

    async def stream(self, messages: list[LLMMessage]) -> AsyncIterator[LLMStreamChunk]:
        try:
            async for chunk in self.primary.stream(messages):
                yield chunk
        except LLMProviderError as exc:
            if not exc.retryable:
                raise
            logger.warning(
                "primary_llm_stream_failed_trying_fallback",
                extra={"provider": self.primary.name, "error_code": exc.code},
            )
            async for chunk in self.fallback.stream(messages):
                yield chunk

    async def list_models(self) -> list[str]:
        primary = await self.primary.list_models()
        fallback = await self.fallback.list_models()
        return [*primary, *fallback]
