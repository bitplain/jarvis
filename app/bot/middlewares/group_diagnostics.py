import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from app.bot.routers.groups import GROUP_CHAT_TYPES, _mask_int, classify_group_message
from app.core.config import Settings
from app.core.logging import safe_extra

logger = logging.getLogger(__name__)


class GroupDiagnosticsMiddleware(BaseMiddleware):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        chat = getattr(event, "chat", None)
        chat_type = getattr(chat, "type", None)
        if chat_type in GROUP_CHAT_TYPES:
            event_any: Any = event
            reply_user_id = None
            reply_to_message = getattr(event_any, "reply_to_message", None)
            if reply_to_message and reply_to_message.from_user:
                reply_user_id = reply_to_message.from_user.id
            bot_user_id, bot_username = await self._resolve_bot_identity(data)
            decision = classify_group_message(
                getattr(event_any, "text", None) or getattr(event_any, "caption", None),
                reply_user_id,
                bot_username or self.settings.telegram_bot_username,
                bot_user_id=bot_user_id,
            )
            log_kwargs: dict[str, Any] = safe_extra(
                update_type="message",
                chat_type=chat_type,
                chat_id_masked=_mask_int(getattr(chat, "id", None)),
                message_id=getattr(event_any, "message_id", None),
                from_user_masked=_mask_int(
                    event_any.from_user.id if event_any.from_user else None
                ),
                text_classification=decision.text_classification,
                matched_bot_username=decision.matched_bot_username,
                should_process=decision.should_process,
            )
            logger.info(
                "group_message_update",
                **log_kwargs,
            )
        return await handler(event, data)

    async def _resolve_bot_identity(self, data: dict[str, Any]) -> tuple[int | None, str | None]:
        bot = data.get("bot")
        if bot is None:
            return None, None
        try:
            me = await bot.get_me()
        except Exception:
            return None, None
        return int(me.id), getattr(me, "username", None)
