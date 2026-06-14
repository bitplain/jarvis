from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal

LLMRole = Literal["system", "user", "assistant"]


@dataclass(frozen=True)
class LLMMessage:
    role: LLMRole
    content: str


@dataclass(frozen=True)
class LLMResponse:
    content: str
    provider: str
    model: str


@dataclass(frozen=True)
class LLMStreamChunk:
    content: str
    provider: str
    model: str
    done: bool = False


LLMStream = AsyncIterator[LLMStreamChunk]
