from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field
from typing import Protocol

from app.core.config import Settings
from app.llm.base import LLMProviderError
from app.llm.fallback import FallbackLLMProvider
from app.llm.openrouter import OpenRouterProvider
from app.llm.types import LLMMessage, LLMResponse
from app.llm.yandex import YandexAIStudioProvider


class Completer(Protocol):
    name: str

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        ...


@dataclass
class SmokeResult:
    statuses: dict[str, str] = field(default_factory=dict)
    verdict: str = "BLOCKED_LLM_SMOKE"

    def render_sanitized(self) -> str:
        lines = ["Stage 1R LLM smoke sanitized result:"]
        for key in sorted(self.statuses):
            lines.append(f"{key}: {self.statuses[key]}")
        lines.append(f"verdict: {self.verdict}")
        return "\n".join(lines)


class RetryableFailingProvider:
    name = "forced-yandex"

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        del max_tokens
        raise LLMProviderError("forced_failure", retryable=True)


async def _check_provider(name: str, provider: Completer, result: SmokeResult) -> bool:
    try:
        response = await provider.complete(
            [LLMMessage(role="user", content="Ответь одним словом: тест")]
        )
    except LLMProviderError as exc:
        result.statuses[name] = f"BLOCKED:{exc.code}"
        return False
    except Exception:
        result.statuses[name] = "BLOCKED:unexpected_error"
        return False
    if not response.content.strip():
        result.statuses[name] = "BLOCKED:empty_response"
        return False
    result.statuses[name] = "OK"
    return True


async def run_smoke(
    *,
    yandex: Completer,
    openrouter: Completer,
    forced_primary: Completer | None = None,
    forced_fallback: Completer | None = None,
) -> SmokeResult:
    result = SmokeResult()
    yandex_ok = await _check_provider("yandex", yandex, result)
    openrouter_ok = await _check_provider("openrouter", openrouter, result)
    fallback = FallbackLLMProvider(
        primary=forced_primary or RetryableFailingProvider(),
        fallback=forced_fallback or openrouter,
    )
    fallback_ok = await _check_provider("forced_fallback", fallback, result)
    if yandex_ok and openrouter_ok and fallback_ok:
        result.verdict = "PASS_LLM_SMOKE"
    elif yandex_ok and fallback_ok:
        result.verdict = "PARTIAL_LLM_SMOKE_OPENROUTER_BLOCKED"
    else:
        result.verdict = "BLOCKED_LLM_SMOKE"
    return result


async def async_main() -> int:
    settings = Settings()
    result = await run_smoke(
        yandex=YandexAIStudioProvider(settings),
        openrouter=OpenRouterProvider(settings),
    )
    print(result.render_sanitized())  # noqa: T201
    return 0 if result.verdict == "PASS_LLM_SMOKE" else 2


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    sys.exit(main())
