from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject


def is_admin_user(user_id: int | None, admin_ids: set[int]) -> bool:
    return user_id is not None and user_id in admin_ids


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
            user_id = event.from_user.id if event.from_user else None
            if not is_admin_user(user_id, self.admin_ids):
                await event.answer("Доступ запрещён.")
                return None
        return await handler(event, data)
