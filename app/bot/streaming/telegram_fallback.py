import logging
from typing import Any, Protocol

from aiogram.enums import ChatAction

logger = logging.getLogger(__name__)


class BotWithTyping(Protocol):
    async def send_chat_action(self, **kwargs: object) -> object:
        ...

    async def send_message(self, **kwargs: object) -> object:
        ...

    async def edit_message_text(self, **kwargs: object) -> object:
        ...


class TelegramFallbackTypingSink:
    def __init__(self, bot: BotWithTyping) -> None:
        self.bot = bot

    async def typing(self, *, chat_id: int) -> None:
        await self.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    async def final(self, *, chat_id: int, text: str) -> None:
        await self.bot.send_message(chat_id=chat_id, text=text)


class TelegramGroupEditSink:
    def __init__(
        self,
        bot: Any,
        *,
        edit_interval_ms: int = 1000,
        chat_action_interval_seconds: int = 4,
        provisional_text: str = "Думаю...",
        business_connection_id: str | None = None,
    ) -> None:
        self.bot = bot
        self.edit_interval_seconds = edit_interval_ms / 1000
        self.chat_action_interval_seconds = chat_action_interval_seconds
        self.provisional_text = provisional_text
        self.business_connection_id = business_connection_id
        self.message_id: int | None = None
        self.last_edit_at: float | None = None
        self.last_chat_action_at: float | None = None

    async def start(self, *, chat_id: int, now: float = 0.0) -> None:
        await self._send_chat_action(chat_id=chat_id)
        self.last_chat_action_at = now
        message = await self.bot.send_message(chat_id=chat_id, text=self.provisional_text)
        self.message_id = int(message.message_id)

    async def publish(self, *, chat_id: int, text: str, now: float) -> None:
        if self.message_id is None:
            await self.start(chat_id=chat_id, now=now)
        if (
            self.last_chat_action_at is None
            or now - self.last_chat_action_at >= self.chat_action_interval_seconds
        ):
            await self._send_chat_action(chat_id=chat_id)
            self.last_chat_action_at = now
        if self.last_edit_at is not None and now - self.last_edit_at < self.edit_interval_seconds:
            return
        await self._edit(chat_id=chat_id, text=text)
        self.last_edit_at = now

    async def final(self, *, chat_id: int, text: str) -> None:
        if self.message_id is None:
            await self.start(chat_id=chat_id)
        try:
            await self._edit(chat_id=chat_id, text=text)
        except Exception as exc:
            logger.warning(
                "telegram_streaming_final_edit_failed",
                extra={"error_type": type(exc).__name__},
            )
            await self.bot.send_message(chat_id=chat_id, text=text)

    async def _send_chat_action(self, *, chat_id: int) -> None:
        payload: dict[str, object] = {"chat_id": chat_id, "action": ChatAction.TYPING.value}
        if self.business_connection_id is not None:
            payload["business_connection_id"] = self.business_connection_id
        await self.bot.send_chat_action(**payload)

    async def _edit(self, *, chat_id: int, text: str) -> None:
        await self.bot.edit_message_text(chat_id=chat_id, message_id=self.message_id, text=text)
