from abc import ABC, abstractmethod

from app.llm.types import LLMMessage, LLMResponse, LLMStream


class LLMProviderError(Exception):
    def __init__(self, code: str, *, retryable: bool) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


class LLMProvider(ABC):
    name: str

    @abstractmethod
    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        raise NotImplementedError

    @abstractmethod
    def stream(self, messages: list[LLMMessage]) -> LLMStream:
        raise NotImplementedError

    @abstractmethod
    async def list_models(self) -> list[str]:
        raise NotImplementedError
