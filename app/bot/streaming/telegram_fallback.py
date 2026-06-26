import logging
from typing import Any, Protocol

from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramBadRequest

from app.bot.streaming.text_limits import clip_telegram_preview, split_telegram_text
from app.bot.thinking import THINKING_TEXT

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
        provisional_text: str = THINKING_TEXT,
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
        self.final_delivered = False

    async def start(self, *, chat_id: int, now: float = 0.0) -> None:
        await self._send_chat_action(chat_id=chat_id)
        self.last_chat_action_at = now
        message = await self.bot.send_message(chat_id=chat_id, text=self.provisional_text)
        self.message_id = int(message.message_id)
        logger.warning(
            "telegram_group_provisional_sent",
            extra={"message_id": self.message_id, "text_length": len(self.provisional_text)},
        )

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
        if self.final_delivered:
            logger.warning(
                "telegram_group_final_already_delivered",
                extra={"message_id": self.message_id, "source_text_length": len(text)},
            )
            return
        if self.message_id is None:
            await self.start(chat_id=chat_id)
        chunks = split_telegram_text(text)
        try:
            logger.warning(
                "telegram_group_final_edit_called",
                extra={"message_id": self.message_id, "text_length": len(chunks[0])},
            )
            await self._edit(chat_id=chat_id, text=chunks[0])
        except TelegramBadRequest as exc:
            if _is_message_not_modified(exc):
                logger.warning(
                    "telegram_group_final_message_not_modified",
                    extra={"message_id": self.message_id, "text_length": len(chunks[0])},
                )
                await self._send_remaining_chunks(
                    chat_id=chat_id,
                    chunks=chunks,
                    source_text_length=len(text),
                )
                self.final_delivered = True
                return
            logger.warning(
                "telegram_streaming_final_edit_failed",
                extra={"error_type": type(exc).__name__},
            )
            await self._send_final_chunks(
                chat_id=chat_id,
                chunks=chunks,
                source_text_length=len(text),
            )
            self.final_delivered = True
            return
        except Exception as exc:
            logger.warning(
                "telegram_streaming_final_edit_failed",
                extra={"error_type": type(exc).__name__},
            )
            await self._send_final_chunks(
                chat_id=chat_id,
                chunks=chunks,
                source_text_length=len(text),
            )
            self.final_delivered = True
            return
        logger.warning(
            "telegram_group_final_edit_succeeded",
            extra={"message_id": self.message_id, "text_length": len(chunks[0])},
        )
        await self._send_remaining_chunks(
            chat_id=chat_id,
            chunks=chunks,
            source_text_length=len(text),
        )
        self.final_delivered = True

    async def _send_remaining_chunks(
        self,
        *,
        chat_id: int,
        chunks: list[str],
        source_text_length: int,
    ) -> None:
        for index, chunk in enumerate(chunks[1:], start=2):
            await self.bot.send_message(chat_id=chat_id, text=chunk)
            logger.warning(
                "telegram_group_final_send_fallback_called",
                extra={
                    "chunk_index": index,
                    "chunk_count": len(chunks),
                    "text_length": len(chunk),
                    "source_text_length": source_text_length,
                },
            )

    async def _send_final_chunks(
        self,
        *,
        chat_id: int,
        chunks: list[str],
        source_text_length: int,
    ) -> None:
        for index, chunk in enumerate(chunks, start=1):
            await self.bot.send_message(chat_id=chat_id, text=chunk)
            logger.warning(
                "telegram_group_final_send_fallback_called",
                extra={
                    "chunk_index": index,
                    "chunk_count": len(chunks),
                    "text_length": len(chunk),
                    "source_text_length": source_text_length,
                },
            )

    async def _send_chat_action(self, *, chat_id: int) -> None:
        payload: dict[str, object] = {"chat_id": chat_id, "action": ChatAction.TYPING.value}
        if self.business_connection_id is not None:
            payload["business_connection_id"] = self.business_connection_id
        await self.bot.send_chat_action(**payload)
        logger.warning(
            "telegram_send_chat_action_called",
            extra={"action": ChatAction.TYPING.value},
        )

    async def _edit(self, *, chat_id: int, text: str) -> None:
        preview_text = clip_telegram_preview(text)
        await self.bot.edit_message_text(
            chat_id=chat_id,
            message_id=self.message_id,
            text=preview_text,
        )
        logger.warning(
            "telegram_group_edit_message_text_called",
            extra={
                "message_id": self.message_id,
                "text_length": len(preview_text),
                "source_text_length": len(text),
            },
        )


def _is_message_not_modified(exc: TelegramBadRequest) -> bool:
    return "message is not modified" in str(exc).lower()
