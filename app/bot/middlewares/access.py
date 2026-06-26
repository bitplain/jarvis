import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypedDict

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from app.bot.routers.groups import classify_group_message
from app.core.logging import safe_extra
from app.db.repositories.telegram_access import TelegramAccessRepository
from app.services.telegram_access_service import TelegramAccessService

logger = logging.getLogger(__name__)
GROUP_CHAT_TYPES = {"group", "supergroup"}
WHOAMI_COMMAND = "/whoami"


class AccessDecision(TypedDict):
    allowed: bool
    is_user_allowed: bool
    has_group_allowlist: bool
    is_group_allowed: bool
    reason: str


def is_admin_user(user_id: int | None, admin_ids: set[int]) -> bool:
    return user_id is not None and user_id in admin_ids


def is_whoami_command(message: Message) -> bool:
    text = message.text or message.caption
    if not text:
        return False
    command = text.strip().split(maxsplit=1)[0].lower()
    return command == WHOAMI_COMMAND or command.startswith(f"{WHOAMI_COMMAND}@")


def _mask_int(value: int | None) -> str:
    if value is None:
        return "missing"
    text = str(value)
    prefix = "-" if text.startswith("-") else ""
    digits = text[1:] if prefix else text
    tail = digits[-4:] if len(digits) > 4 else digits
    return f"{prefix}***{tail}"


def _log_access_decision(
    *,
    message: Message,
    user_id: int | None,
    is_admin: bool,
    is_user_allowed: bool,
    has_group_allowlist: bool,
    is_group_allowed: bool,
    is_mention_or_reply: bool,
    decision: str,
    reason: str,
) -> None:
    log_kwargs: dict[str, Any] = safe_extra(
        chat_type=message.chat.type,
        chat_id=_mask_int(message.chat.id),
        user_id=_mask_int(user_id),
        is_admin=is_admin,
        is_user_allowed=is_user_allowed,
        has_group_allowlist=has_group_allowlist,
        is_group_allowed=is_group_allowed,
        is_mention_or_reply=is_mention_or_reply,
        decision=decision,
        reason=reason,
    )
    logger.info(
        "telegram_access_decision",
        **log_kwargs,
    )


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
            is_admin = is_admin_user(user_id, self.admin_ids)
            if is_whoami_command(event):
                _log_access_decision(
                    message=event,
                    user_id=user_id,
                    is_admin=is_admin,
                    is_user_allowed=False,
                    has_group_allowlist=False,
                    is_group_allowed=False,
                    is_mention_or_reply=True,
                    decision="allow",
                    reason="whoami_bypass",
                )
                return await handler(event, data)
            if event.chat.type in GROUP_CHAT_TYPES:
                is_mention_or_reply = await self._is_group_mention_or_reply(event, data)
                if not is_mention_or_reply:
                    _log_access_decision(
                        message=event,
                        user_id=user_id,
                        is_admin=is_admin,
                        is_user_allowed=False,
                        has_group_allowlist=False,
                        is_group_allowed=False,
                        is_mention_or_reply=False,
                        decision="ignore_no_trigger",
                        reason="ignored_no_trigger",
                    )
                    return None
            else:
                is_mention_or_reply = False
            if is_admin:
                _log_access_decision(
                    message=event,
                    user_id=user_id,
                    is_admin=True,
                    is_user_allowed=True,
                    has_group_allowlist=False,
                    is_group_allowed=True,
                    is_mention_or_reply=is_mention_or_reply,
                    decision="allow",
                    reason="allowed_admin",
                )
                return await handler(event, data)
            access_decision = await self._db_access_decision(event, user_id, data)
            if access_decision["allowed"]:
                _log_access_decision(
                    message=event,
                    user_id=user_id,
                    is_admin=False,
                    is_user_allowed=access_decision["is_user_allowed"],
                    has_group_allowlist=access_decision["has_group_allowlist"],
                    is_group_allowed=access_decision["is_group_allowed"],
                    is_mention_or_reply=is_mention_or_reply,
                    decision="allow",
                    reason="allowed_user",
                )
                return await handler(event, data)
            if event.chat.type in GROUP_CHAT_TYPES:
                reason = str(access_decision["reason"])
                _log_access_decision(
                    message=event,
                    user_id=user_id,
                    is_admin=False,
                    is_user_allowed=access_decision["is_user_allowed"],
                    has_group_allowlist=access_decision["has_group_allowlist"],
                    is_group_allowed=access_decision["is_group_allowed"],
                    is_mention_or_reply=is_mention_or_reply,
                    decision="deny_silent",
                    reason=reason,
                )
                logger.info(
                    "telegram_access_denied_group_silent",
                    extra={"chat_type": event.chat.type},
                )
                return None
            _log_access_decision(
                message=event,
                user_id=user_id,
                is_admin=False,
                is_user_allowed=access_decision["is_user_allowed"],
                has_group_allowlist=access_decision["has_group_allowlist"],
                is_group_allowed=access_decision["is_group_allowed"],
                is_mention_or_reply=is_mention_or_reply,
                decision="deny_private",
                reason=str(access_decision["reason"]),
            )
            logger.info("telegram_access_denied_private")
            await event.answer("Доступ запрещён.")
            return None
        return await handler(event, data)

    async def _is_group_mention_or_reply(self, event: Message, data: dict[str, Any]) -> bool:
        reply_user_id = None
        if event.reply_to_message and event.reply_to_message.from_user:
            reply_user_id = event.reply_to_message.from_user.id
        bot = data.get("bot")
        settings = data.get("settings")
        bot_user_id = None
        bot_username = getattr(settings, "telegram_bot_username", "")
        if bot is not None:
            try:
                me = await bot.get_me()
            except Exception:
                me = None
            if me is not None:
                bot_user_id = getattr(me, "id", None)
                bot_username = getattr(me, "username", None) or bot_username
        decision = classify_group_message(
            event.text,
            reply_user_id,
            str(bot_username),
            bot_user_id=bot_user_id,
        )
        return decision.should_process or decision.needs_query_after_mention

    async def _db_access_decision(
        self,
        event: Message,
        user_id: int | None,
        data: dict[str, Any],
    ) -> AccessDecision:
        session = data.get("db_session")
        if session is None:
            return {
                "allowed": False,
                "is_user_allowed": False,
                "has_group_allowlist": False,
                "is_group_allowed": False,
                "reason": "denied_user",
            }
        try:
            service = TelegramAccessService(
                TelegramAccessRepository(session),
                admin_ids=self.admin_ids,
            )
            is_user_allowed = await service.is_allowed_user(user_id)
            has_group_allowlist = False
            is_group_allowed = event.chat.type not in GROUP_CHAT_TYPES
            if event.chat.type in GROUP_CHAT_TYPES:
                allowed_groups = await service.list_allowed_groups()
                has_group_allowlist = bool(allowed_groups)
                is_group_allowed = not has_group_allowlist or any(
                    entry.telegram_id == event.chat.id for entry in allowed_groups
                )
            allowed = is_user_allowed and is_group_allowed
            reason = "allowed_user"
            if not is_user_allowed:
                reason = "denied_user"
            elif not is_group_allowed:
                reason = "denied_group"
            return {
                "allowed": allowed,
                "is_user_allowed": is_user_allowed,
                "has_group_allowlist": has_group_allowlist,
                "is_group_allowed": is_group_allowed,
                "reason": reason,
            }
        except Exception as exc:
            logger.warning(
                "telegram_access_check_failed",
                extra={"chat_type": event.chat.type, "error_type": type(exc).__name__},
            )
            return {
                "allowed": False,
                "is_user_allowed": False,
                "has_group_allowlist": False,
                "is_group_allowed": False,
                "reason": "access_db_error",
            }
