import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from app.db.repositories.telegram_access import TelegramAccessRepository
from app.services.telegram_access_service import TelegramAccessService

logger = logging.getLogger(__name__)
GROUP_CHAT_TYPES = {"group", "supergroup"}
WHOAMI_COMMAND = "/whoami"


def is_admin_user(user_id: int | None, admin_ids: set[int]) -> bool:
    return user_id is not None and user_id in admin_ids


def is_whoami_command(message: Message) -> bool:
    text = message.text or message.caption
    if not text:
        return False
    command = text.strip().split(maxsplit=1)[0].lower()
    return command == WHOAMI_COMMAND or command.startswith(f"{WHOAMI_COMMAND}@")


class AdminAccessMiddleware(BaseMiddleware):
    def __init__(self, admin_ids: set[int]) -> None:
        self.admin_ids = admin_ids

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message):
            if is_whoami_command(event):
                return await handler(event, data)
            user_id = event.from_user.id if event.from_user else None
            if is_admin_user(user_id, self.admin_ids):
                return await handler(event, data)
            if await self._is_db_allowed(event, user_id, data):
                return await handler(event, data)
            if event.chat.type in GROUP_CHAT_TYPES:
                logger.info(
                    "telegram_access_denied_group_silent",
                    extra={"chat_type": event.chat.type},
                )
                return None
            logger.info("telegram_access_denied_private")
            await event.answer("Доступ запрещён.")
            return None
        return await handler(event, data)

    async def _is_db_allowed(
        self,
        event: Message,
        user_id: int | None,
        data: dict[str, Any],
    ) -> bool:
        session = data.get("db_session")
        if session is None:
            return False
        try:
            service = TelegramAccessService(
                TelegramAccessRepository(session),
                admin_ids=self.admin_ids,
            )
            if not await service.is_allowed_user(user_id):
                return False
            if event.chat.type in GROUP_CHAT_TYPES:
                return await service.is_allowed_group(event.chat.id)
            return True
        except Exception as exc:
            logger.warning(
                "telegram_access_check_failed",
                extra={"chat_type": event.chat.type, "error_type": type(exc).__name__},
            )
            return False
