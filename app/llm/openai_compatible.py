import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.llm.base import LLMProvider, LLMProviderError
from app.llm.model_discovery import parse_openai_models_response
from app.llm.types import LLMMessage, LLMResponse, LLMStreamChunk


class OpenAICompatibleProvider(LLMProvider):
    def __init__(
        self,
        *,
        name: str,
        base_url: str,
        api_key: str,
        model: str,
        extra_headers: dict[str, str] | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.extra_headers = extra_headers or {}
        self.timeout = timeout

    def _ensure_configured(self) -> None:
        if not self.base_url or not self.api_key or not self.model:
            raise LLMProviderError("provider_not_configured", retryable=False)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            **self.extra_headers,
        }

    def _payload(self, messages: list[LLMMessage], *, stream: bool) -> dict[str, Any]:
        return {
            "model": self.model,
            "messages": [
                {"role": message.role, "content": message.content} for message in messages
            ],
            "stream": stream,
        }

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        retryable = response.status_code in {401, 403, 408, 409, 429, 500, 502, 503, 504}
        code = "provider_http_error"
        if response.status_code in {401, 403}:
            code = "auth_error"
        elif response.status_code == 429:
            code = "rate_limited"
        elif response.status_code in {404, 422}:
            code = "model_unavailable"
        elif response.status_code >= 500:
            code = "server_error"
        raise LLMProviderError(code, retryable=retryable)

    async def complete(self, messages: list[LLMMessage]) -> LLMResponse:
        self._ensure_configured()
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=self._headers(),
                    json=self._payload(messages, stream=False),
                )
            self._raise_for_status(response)
            payload = response.json()
        except LLMProviderError:
            raise
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            raise LLMProviderError("network_error", retryable=True) from exc
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMProviderError("invalid_response", retryable=True) from exc
        return LLMResponse(content=str(content), provider=self.name, model=self.model)

    async def stream(self, messages: list[LLMMessage]) -> AsyncIterator[LLMStreamChunk]:
        self._ensure_configured()
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    headers=self._headers(),
                    json=self._payload(messages, stream=True),
                ) as response:
                    self._raise_for_status(response)
                    async for line in response.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data = line.removeprefix("data: ").strip()
                        if data == "[DONE]":
                            yield LLMStreamChunk(
                                content="", provider=self.name, model=self.model, done=True
                            )
                            break
                        try:
                            payload = json.loads(data)
                            delta = payload["choices"][0].get("delta", {})
                            content = delta.get("content", "")
                        except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                            continue
                        if content:
                            yield LLMStreamChunk(
                                content=str(content), provider=self.name, model=self.model
                            )
        except LLMProviderError:
            raise
        except httpx.HTTPError as exc:
            raise LLMProviderError("network_error", retryable=True) from exc

    async def list_models(self) -> list[str]:
        if not self.base_url or not self.api_key:
            return []
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.get(f"{self.base_url}/models", headers=self._headers())
            self._raise_for_status(response)
            return parse_openai_models_response(response.json())
        except (LLMProviderError, httpx.HTTPError, json.JSONDecodeError):
            return []
