import logging
import secrets
from collections.abc import Awaitable, Callable
from typing import Any, Protocol, cast

from app.bot.adapters.message_draft_api import TelegramMessageDraftApi
from app.bot.streaming.text_limits import clip_telegram_preview

logger = logging.getLogger(__name__)


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
        draft_id: int | None = None,
        raw_call: RawTelegramCall | None = None,
        timeout: float = 15.0,
        raw_api_fallback: bool = True,
    ) -> None:
        self.bot = bot
        self.draft_id = draft_id or self.generate_draft_id()
        self.raw_call = raw_call
        self.timeout = timeout
        self.raw_api_fallback = raw_api_fallback
        self.available = True

    @staticmethod
    def generate_draft_id() -> int:
        return max(1, secrets.randbits(31))

    async def start(self, *, chat_id: int, message_thread_id: int | None = None) -> None:
        await self.publish(chat_id=chat_id, text="", message_thread_id=message_thread_id)

    async def publish(
        self,
        *,
        chat_id: int,
        text: str,
        message_thread_id: int | None = None,
    ) -> None:
        if not self.available:
            raise TelegramDraftNotAvailable("draft_disabled_for_job")
        preview_text = clip_telegram_preview(text)
        typed_method = getattr(self.bot, "send_message_draft", None)
        if callable(typed_method):
            try:
                payload: dict[str, object] = {
                    "chat_id": chat_id,
                    "draft_id": self.draft_id,
                    "text": preview_text,
                }
                if message_thread_id is not None:
                    payload["message_thread_id"] = message_thread_id
                await typed_method(**payload)
                logger.warning(
                    "telegram_send_message_draft_called",
                    extra={
                        "draft_id": self.draft_id,
                        "text_length": len(preview_text),
                        "source_text_length": len(text),
                        "empty_text": preview_text == "",
                        "adapter": "typed",
                    },
                )
                return
            except Exception as exc:
                if preview_text == "":
                    logger.warning(
                        "telegram_empty_draft_placeholder_skipped",
                        extra={"draft_id": self.draft_id, "error_type": type(exc).__name__},
                    )
                    return
                self._disable("typed_draft_failed", exc)
                raise TelegramDraftNotAvailable("typed_draft_failed") from exc
        if not self.raw_api_fallback:
            self._disable("typed_draft_missing", None)
            raise TelegramDraftNotAvailable("typed_draft_missing")
        try:
            payload = {"chat_id": chat_id, "draft_id": self.draft_id, "text": preview_text}
            if message_thread_id is not None:
                payload["message_thread_id"] = message_thread_id
            result = await self._raw("sendMessageDraft", payload)
        except Exception as exc:
            if preview_text == "":
                logger.warning(
                    "telegram_empty_draft_placeholder_skipped",
                    extra={"draft_id": self.draft_id, "error_type": type(exc).__name__},
                )
                return
            self._disable("raw_draft_failed", exc)
            raise TelegramDraftNotAvailable("raw_draft_failed") from exc
        if result.get("ok") is not True:
            if preview_text == "":
                logger.warning(
                    "telegram_empty_draft_placeholder_skipped",
                    extra={"draft_id": self.draft_id, "error_type": None},
                )
                return
            self._disable("raw_draft_not_ok", None)
            raise TelegramDraftNotAvailable("raw_draft_not_ok")
        logger.warning(
            "telegram_send_message_draft_called",
            extra={
                "draft_id": self.draft_id,
                "text_length": len(preview_text),
                "source_text_length": len(text),
                "empty_text": preview_text == "",
                "adapter": "raw",
            },
        )

    async def final(self, *, chat_id: int, text: str) -> None:
        await self.bot.send_message(chat_id=chat_id, text=text)  # type: ignore[attr-defined]

    async def _raw(self, method: str, payload: dict[str, object]) -> dict[str, Any]:
        if self.raw_call is not None:
            return await self.raw_call(method, payload)
        if method != "sendMessageDraft":
            return {"ok": False}
        adapter = TelegramMessageDraftApi(self.bot, timeout=self.timeout)
        message_thread_id = payload.get("message_thread_id")
        return await adapter.send_message_draft(
            chat_id=int(cast(int | str, payload["chat_id"])),
            draft_id=int(cast(int | str, payload["draft_id"])),
            text=str(payload.get("text", "")),
            message_thread_id=(
                int(cast(int | str, message_thread_id))
                if message_thread_id is not None
                else None
            ),
        )

    def _disable(self, reason: str, exc: BaseException | None) -> None:
        self.available = False
        logger.warning(
            "telegram_draft_disabled_for_job",
            extra={"reason": reason, "error_type": type(exc).__name__ if exc else None},
        )
