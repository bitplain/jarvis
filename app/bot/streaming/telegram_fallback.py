from typing import Protocol

from aiogram.enums import ChatAction


class BotWithTyping(Protocol):
    async def send_chat_action(self, *, chat_id: int, action: ChatAction) -> object:
        ...

    async def send_message(self, *, chat_id: int, text: str) -> object:
        ...


class TelegramFallbackTypingSink:
    def __init__(self, bot: BotWithTyping) -> None:
        self.bot = bot

    async def typing(self, *, chat_id: int) -> None:
        await self.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    async def final(self, *, chat_id: int, text: str) -> None:
        await self.bot.send_message(chat_id=chat_id, text=text)
