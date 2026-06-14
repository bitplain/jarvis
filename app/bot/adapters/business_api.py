from typing import Any

from aiogram import Bot
from aiogram.types import BusinessConnection

from app.services.business_service import BusinessConnectionEvent


def business_connection_event_from_aiogram(
    connection: BusinessConnection,
) -> BusinessConnectionEvent:
    rights = connection.rights.model_dump(exclude_none=True) if connection.rights else {}
    can_reply = bool(connection.can_reply or rights.get("can_reply"))
    can_read_messages = bool(rights.get("can_read_messages"))
    return BusinessConnectionEvent(
        business_connection_id=connection.id,
        business_user_id=connection.user.id if connection.user else None,
        user_chat_id=connection.user_chat_id,
        is_enabled=connection.is_enabled,
        can_reply=can_reply,
        can_read_messages=can_read_messages,
        rights_json=rights,
    )


class AiogramBusinessApi:
    def __init__(self, bot: Bot | Any) -> None:
        self.bot = bot

    async def get_business_connection(self, business_connection_id: str) -> BusinessConnectionEvent:
        connection = await self.bot.get_business_connection(
            business_connection_id=business_connection_id
        )
        return business_connection_event_from_aiogram(connection)

    async def send_business_message(
        self,
        *,
        business_connection_id: str,
        chat_id: int,
        text: str,
    ) -> None:
        await self.bot.send_message(
            chat_id=chat_id,
            text=text,
            business_connection_id=business_connection_id,
        )

    async def mark_business_message_read(self) -> None:
        raise NotImplementedError("mark-read не используется в Stage 3A.")
