import logging
import re
from dataclasses import dataclass
from typing import Any

from aiogram import F, Router
from aiogram.enums import ChatAction
from aiogram.types import Message

from app.core.logging import safe_extra
from app.db.models import MessageRole
from app.db.repositories.messages import MessageRepository
from app.services.memory_service import MemoryService

logger = logging.getLogger(__name__)
GROUP_CHAT_TYPES = {"group", "supergroup"}
MENTION_QUERY_REQUIRED = "Напиши запрос после упоминания бота."


@dataclass(frozen=True)
class GroupMessageDecision:
    text_classification: str
    matched_bot_username: bool
    should_process: bool
    needs_query_after_mention: bool = False


def _normalize_bot_username(bot_username: str) -> str:
    return bot_username.strip().lstrip("@").lower()


def _mask_int(value: int | None) -> str:
    if value is None:
        return "missing"
    text = str(value)
    prefix = "-" if text.startswith("-") else ""
    digits = text[1:] if prefix else text
    tail = digits[-4:] if len(digits) > 4 else digits
    return f"{prefix}***{tail}"


def _command_mention_username(text: str) -> str | None:
    match = re.match(r"^/[A-Za-z0-9_]+@([A-Za-z0-9_]+)(?:\s|$)", text.strip())
    if not match:
        return None
    return match.group(1).lower()


def _mentions_bot(text: str, bot_username: str) -> bool:
    username = _normalize_bot_username(bot_username)
    if not username:
        return False
    pattern = rf"(?<![A-Za-z0-9_])@{re.escape(username)}(?![A-Za-z0-9_])"
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def _text_after_mention(text: str, bot_username: str) -> str:
    username = _normalize_bot_username(bot_username)
    pattern = rf"(?<![A-Za-z0-9_])@{re.escape(username)}(?![A-Za-z0-9_])"
    return re.sub(pattern, "", text, flags=re.IGNORECASE).strip()


def should_answer_group_message(
    text: str | None,
    reply_to_user_id: int | None,
    bot_username: str,
    *,
    bot_user_id: int | None = None,
) -> bool:
    return classify_group_message(
        text,
        reply_to_user_id,
        bot_username,
        bot_user_id=bot_user_id,
    ).should_process


def classify_group_message(
    text: str | None,
    reply_to_user_id: int | None,
    bot_username: str,
    *,
    bot_user_id: int | None = None,
) -> GroupMessageDecision:
    if not text:
        return GroupMessageDecision("plain", False, False)
    command_username = _command_mention_username(text)
    normalized_username = _normalize_bot_username(bot_username)
    if command_username is not None:
        matched = bool(normalized_username) and command_username == normalized_username
        return GroupMessageDecision("command_mention", matched, matched)
    if _mentions_bot(text, bot_username):
        has_query = bool(_text_after_mention(text, bot_username))
        if not has_query:
            return GroupMessageDecision("empty_mention", True, False, True)
        return GroupMessageDecision("mention", True, True)
    if bot_user_id is not None and reply_to_user_id == bot_user_id:
        return GroupMessageDecision("reply_to_bot", False, True)
    return GroupMessageDecision("plain", False, False)


def _log_group_routing(
    *,
    message: Message,
    decision: GroupMessageDecision,
    enqueue_job: bool,
) -> None:
    log_kwargs: dict[str, Any] = safe_extra(
        update_type="message",
        chat_type=message.chat.type,
        chat_id_masked=_mask_int(message.chat.id),
        message_id=message.message_id,
        from_user_masked=_mask_int(message.from_user.id if message.from_user else None),
        text_classification=decision.text_classification,
        matched_bot_username=decision.matched_bot_username,
        should_process=decision.should_process,
        enqueue_job=enqueue_job,
        worker_job_private=False if enqueue_job else None,
    )
    logger.info(
        "group_message_routing",
        **log_kwargs,
    )


async def handle_group_message(message: Message, **data: Any) -> None:
    if message.chat.type not in GROUP_CHAT_TYPES or not message.from_user:
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
    bot_username = getattr(me, "username", None) or settings.telegram_bot_username
    decision = classify_group_message(
        message.text,
        reply_user_id,
        str(bot_username),
        bot_user_id=bot_user_id,
    )
    if decision.needs_query_after_mention:
        _log_group_routing(message=message, decision=decision, enqueue_job=False)
        await message.answer(MENTION_QUERY_REQUIRED)
        return
    if not decision.should_process:
        _log_group_routing(message=message, decision=decision, enqueue_job=False)
        return
    memory = data.get("memory_service")
    if not isinstance(memory, MemoryService):
        session = data.get("db_session")
        if session is None:
            await message.answer("База данных временно недоступна.")
            return
        memory = MemoryService(
            MessageRepository(session),
            max_messages=settings.memory_max_messages,
        )
    await memory.add_message(
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        role=MessageRole.USER,
        text=message.text or "",
        telegram_message_id=message.message_id,
    )
    redis = data.get("redis")
    if redis is None:
        await message.answer("Worker временно недоступен.")
        return
    job_id = f"llm:{message.chat.id}:{message.message_id}"
    await redis.enqueue_job(
        "process_llm_message",
        {
            "chat_id": message.chat.id,
            "user_id": message.from_user.id,
            "private": False,
        },
        _job_id=job_id,
    )
    log_kwargs: dict[str, Any] = safe_extra(
        chat_type=message.chat.type,
        chat_id_masked=_mask_int(message.chat.id),
        user_id_masked=_mask_int(message.from_user.id),
        message_id=message.message_id,
        private=False,
        job_id=job_id,
    )
    logger.info("telegram_llm_job_enqueued", **log_kwargs)
    _log_group_routing(message=message, decision=decision, enqueue_job=True)
    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)


def build_router() -> Router:
    router = Router(name="groups")
    router.message(F.chat.type.in_(GROUP_CHAT_TYPES))(handle_group_message)
    return router


router = build_router()
