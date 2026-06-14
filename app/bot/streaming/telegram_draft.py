from collections.abc import Awaitable, Callable
from typing import Any, Protocol

import httpx


class TelegramDraftNotAvailable(Exception):
    pass


class BotLike(Protocol):
    @property
    def token(self) -> str:
        ...


RawTelegramCall = Callable[[str, dict[str, object]], Awaitable[dict[str, Any]]]


class TelegramPrivateDraftSink:
    def __init__(
        self,
        bot: BotLike,
        *,
        raw_call: RawTelegramCall | None = None,
        timeout: float = 15.0,
    ) -> None:
        self.bot = bot
        self.raw_call = raw_call
        self.timeout = timeout

    async def publish(self, *, chat_id: int, text: str) -> None:
        typed_method = getattr(self.bot, "send_message_draft", None)
        if callable(typed_method):
            try:
                await typed_method(chat_id=chat_id, text=text)
                return
            except Exception as exc:
                raise TelegramDraftNotAvailable("typed_draft_failed") from exc
        try:
            result = await self._raw("sendMessageDraft", {"chat_id": chat_id, "text": text})
        except Exception as exc:
            raise TelegramDraftNotAvailable("raw_draft_failed") from exc
        if result.get("ok") is not True:
            raise TelegramDraftNotAvailable("raw_draft_not_ok")

    async def _raw(self, method: str, payload: dict[str, object]) -> dict[str, Any]:
        if self.raw_call is not None:
            return await self.raw_call(method, payload)
        url = f"https://api.telegram.org/bot{self.bot.token}/{method}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, json=payload)
        response.raise_for_status()
        payload_json = response.json()
        if isinstance(payload_json, dict):
            return payload_json
        return {"ok": False}
