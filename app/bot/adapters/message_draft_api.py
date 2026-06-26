import secrets
from typing import Any, Protocol

import httpx


class BotTokenLike(Protocol):
    @property
    def token(self) -> str:
        ...


class TelegramMessageDraftApi:
    def __init__(self, bot: BotTokenLike, *, timeout: float = 15.0) -> None:
        self.bot = bot
        self.timeout = timeout

    async def send_message_draft(
        self,
        *,
        chat_id: int,
        draft_id: int | None = None,
        text: str,
        message_thread_id: int | None = None,
    ) -> dict[str, Any]:
        draft_id = draft_id or self.generate_draft_id()
        payload: dict[str, object] = {"chat_id": chat_id, "draft_id": draft_id, "text": text}
        if message_thread_id is not None:
            payload["message_thread_id"] = message_thread_id
        url = f"https://api.telegram.org/bot{self.bot.token}/sendMessageDraft"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, json=payload)
        response.raise_for_status()
        parsed = response.json()
        if isinstance(parsed, dict):
            return parsed
        return {"ok": False}

    async def send_rich_message_draft(
        self,
        *,
        chat_id: int,
        rich_text: dict[str, object],
        draft_id: int | None = None,
        message_thread_id: int | None = None,
    ) -> dict[str, Any]:
        draft_id = draft_id or self.generate_draft_id()
        payload: dict[str, object] = {
            "chat_id": chat_id,
            "draft_id": draft_id,
            "rich_message": rich_text,
        }
        if message_thread_id is not None:
            payload["message_thread_id"] = message_thread_id
        url = f"https://api.telegram.org/bot{self.bot.token}/sendRichMessageDraft"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, json=payload)
        response.raise_for_status()
        parsed = response.json()
        if isinstance(parsed, dict):
            return parsed
        return {"ok": False}

    @staticmethod
    def generate_draft_id() -> int:
        return max(1, secrets.randbits(31))
