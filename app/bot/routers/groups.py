from typing import Any

from aiogram import Router
from aiogram.enums import ChatAction
from aiogram.types import Message


def should_answer_group_message(
    text: str | None,
    reply_to_user_id: int | None,
    bot_username: str,
    *,
    bot_user_id: int | None = None,
) -> bool:
    if not text:
        return False
    if bot_username and f"@{bot_username.lower()}" in text.lower():
        return True
    return bot_user_id is not None and reply_to_user_id == bot_user_id


async def handle_group_message(message: Message, **data: Any) -> None:
    if message.chat.type not in {"group", "supergroup"}:
        return
    settings = data["settings"]
    if not settings.group_assistant_enabled:
        return
    bot = data["bot"]
    reply_user_id = None
    if message.reply_to_message and message.reply_to_message.from_user:
        reply_user_id = message.reply_to_message.from_user.id
    bot_user_id = None
    me = await bot.get_me()
    bot_user_id = me.id
    if not should_answer_group_message(
        message.text,
        reply_user_id,
        settings.telegram_bot_username,
        bot_user_id=bot_user_id,
    ):
        return
    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)
    await message.answer("Групповой ответ будет подготовлен через worker.")


def build_router() -> Router:
    router = Router(name="groups")
    router.message()(handle_group_message)
    return router


router = build_router()
