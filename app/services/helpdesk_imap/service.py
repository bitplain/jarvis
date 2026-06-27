from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from email.utils import parseaddr
from typing import Protocol

from aiogram import Bot

from app.services.helpdesk_imap.client import (
    HelpdeskFetchedEmail,
    HelpdeskImapAuthError,
    HelpdeskImapNetworkError,
)
from app.services.helpdesk_imap.config import HelpdeskImapConfig
from app.services.helpdesk_imap.formatter import build_helpdesk_ticket_card
from app.services.helpdesk_imap.parser import ParsedHelpdeskTicket, parse_glpi_email

logger = logging.getLogger(__name__)

HELPDESK_LAST_CHECK_KEY = "jarvis:helpdesk_imap:last_check"
HELPDESK_LAST_SUCCESS_KEY = "jarvis:helpdesk_imap:last_success"
HELPDESK_LAST_ERROR_KEY = "jarvis:helpdesk_imap:last_error"
HELPDESK_LAST_ATTEMPT_KEY = "jarvis:helpdesk_imap:last_attempt_epoch"
HELPDESK_LOCK_KEY = "jarvis:helpdesk_imap:lock"


class HelpdeskEventRepository(Protocol):
    async def exists(
        self,
        *,
        folder: str,
        imap_uid: str | None,
        message_id: str | None,
    ) -> bool: ...

    async def create_event(self, **values: object) -> str | None: ...

    async def mark_notified(
        self,
        event_id: str,
        *,
        telegram_chat_id: int,
        telegram_message_id: int,
    ) -> None: ...

    async def mark_notify_failed(self, event_id: str, *, error_code: str) -> None: ...


class HelpdeskClient(Protocol):
    async def fetch_recent(self) -> list[HelpdeskFetchedEmail]: ...

    async def mark_seen(self, *, folder: str, uid: str) -> None: ...

    async def close(self) -> None: ...


class HelpdeskNotifier(Protocol):
    async def send_ticket(self, *, chat_id: int, ticket: ParsedHelpdeskTicket) -> int: ...


class RedisLike(Protocol):
    async def get(self, key: str) -> object: ...

    async def set(
        self,
        key: str,
        value: str,
        *,
        ex: int,
        nx: bool = False,
    ) -> object: ...


@dataclass(frozen=True)
class HelpdeskRunResult:
    status: str
    processed: int = 0
    skipped_duplicates: int = 0
    skipped_filtered: int = 0
    failed: int = 0
    error_code: str | None = None


class TelegramHelpdeskNotifier:
    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    async def send_ticket(self, *, chat_id: int, ticket: ParsedHelpdeskTicket) -> int:
        card = build_helpdesk_ticket_card(ticket)
        message = await self.bot.send_message(
            chat_id=chat_id,
            text=card.text,
            parse_mode="HTML",
            reply_markup=card.reply_markup,
        )
        return int(message.message_id)


class HelpdeskImapService:
    def __init__(
        self,
        *,
        config: HelpdeskImapConfig,
        repository: HelpdeskEventRepository,
        client: HelpdeskClient,
        notifier: HelpdeskNotifier,
        redis: RedisLike | None = None,
    ) -> None:
        self.config = config
        self.repository = repository
        self.client = client
        self.notifier = notifier
        self.redis = redis

    async def run_once(self) -> HelpdeskRunResult:
        if not self.config.enabled:
            return HelpdeskRunResult(status="disabled")
        if not self.config.configured:
            logger.warning(
                "helpdesk_imap_config_incomplete",
                extra={
                    "missing": ",".join(self.config.missing_required),
                    "host": "configured" if self.config.host else "missing",
                    "username": self.config.safe_username,
                },
            )
            await record_helpdesk_status(self.redis, last_error="config")
            return HelpdeskRunResult(status="config_incomplete", error_code="config")
        if not await _should_run_now(self.redis, self.config.poll_interval_seconds):
            return HelpdeskRunResult(status="throttled")
        if not await _claim_lock(self.redis, self.config.poll_interval_seconds):
            return HelpdeskRunResult(status="locked")
        await record_helpdesk_status(self.redis, last_error=None)
        processed = 0
        skipped_duplicates = 0
        skipped_filtered = 0
        failed = 0
        last_error = "none"
        try:
            messages = await self.client.fetch_recent()
            for message in messages:
                if not self._candidate_matches(message):
                    skipped_filtered += 1
                    continue
                if await self.repository.exists(
                    folder=message.folder,
                    imap_uid=message.uid,
                    message_id=message.message_id,
                ):
                    skipped_duplicates += 1
                    continue
                result = await self._process_message(message)
                processed += result.processed
                failed += result.failed
                if result.error_code is not None:
                    last_error = result.error_code
            await record_helpdesk_status(self.redis, success=True, last_error=last_error)
        except HelpdeskImapAuthError:
            await record_helpdesk_status(self.redis, last_error="auth")
            logger.warning("helpdesk_imap_auth_failed", extra=self.config.safe_summary())
            return HelpdeskRunResult(status="failed", error_code="auth")
        except HelpdeskImapNetworkError:
            await record_helpdesk_status(self.redis, last_error="network")
            logger.warning("helpdesk_imap_network_failed", extra=self.config.safe_summary())
            return HelpdeskRunResult(status="failed", error_code="network")
        finally:
            await self.client.close()
        return HelpdeskRunResult(
            status="ok",
            processed=processed,
            skipped_duplicates=skipped_duplicates,
            skipped_filtered=skipped_filtered,
            failed=failed,
        )

    def _candidate_matches(self, message: HelpdeskFetchedEmail) -> bool:
        if self.config.subject_prefix and not message.subject.startswith(
            self.config.subject_prefix
        ):
            return False
        if not self.config.from_filter:
            return True
        _, email = parseaddr(message.from_header)
        return email.lower() == self.config.from_filter.lower()

    async def _process_message(self, message: HelpdeskFetchedEmail) -> HelpdeskRunResult:
        ticket = parse_glpi_email(
            subject=message.subject,
            body=message.body,
            from_header=message.from_header,
        )
        notify_status = "pending" if ticket.parse_status == "parsed" else "skipped"
        event_id = await self.repository.create_event(
            message_id=message.message_id,
            imap_uid=message.uid,
            folder=message.folder,
            subject=message.subject,
            from_email_masked=ticket.sender_email_masked,
            received_at=message.received_at,
            glpi_ticket_id=ticket.ticket_id,
            ticket_url=ticket.ticket_url,
            event_type=ticket.event_type,
            parse_status=ticket.parse_status,
            notify_status=notify_status,
            telegram_chat_id=self.config.telegram_chat_id,
            telegram_message_id=None,
            error_code=None if ticket.parse_status == "parsed" else "parse_failed",
        )
        if event_id is None:
            return HelpdeskRunResult(status="duplicate", skipped_duplicates=1)
        if ticket.parse_status != "parsed":
            return HelpdeskRunResult(
                status="parse_failed",
                processed=1,
                failed=1,
                error_code="parse",
            )
        assert self.config.telegram_chat_id is not None
        try:
            message_id = await self.notifier.send_ticket(
                chat_id=self.config.telegram_chat_id,
                ticket=ticket,
            )
        except Exception as exc:
            logger.warning(
                "helpdesk_telegram_send_failed",
                extra={"error_type": type(exc).__name__},
            )
            await self.repository.mark_notify_failed(event_id, error_code="telegram")
            return HelpdeskRunResult(
                status="telegram_failed",
                processed=1,
                failed=1,
                error_code="telegram",
            )
        await self.repository.mark_notified(
            event_id,
            telegram_chat_id=self.config.telegram_chat_id,
            telegram_message_id=message_id,
        )
        if self.config.mark_seen and message.uid:
            try:
                await self.client.mark_seen(folder=message.folder, uid=message.uid)
            except HelpdeskImapNetworkError as exc:
                logger.warning(
                    "helpdesk_imap_mark_seen_failed",
                    extra={"error_type": type(exc).__name__},
                )
        return HelpdeskRunResult(status="sent", processed=1)


async def record_helpdesk_status(
    redis: RedisLike | None,
    *,
    success: bool = False,
    last_error: str | None = None,
) -> None:
    if redis is None:
        return
    now = _now_iso()
    try:
        await redis.set(HELPDESK_LAST_CHECK_KEY, now, ex=7 * 24 * 60 * 60)
        if success:
            await redis.set(HELPDESK_LAST_SUCCESS_KEY, now, ex=7 * 24 * 60 * 60)
        if last_error is not None:
            await redis.set(HELPDESK_LAST_ERROR_KEY, last_error, ex=7 * 24 * 60 * 60)
    except Exception as exc:
        logger.warning(
            "helpdesk_imap_status_store_failed",
            extra={"error_type": type(exc).__name__},
        )


async def _should_run_now(redis: RedisLike | None, interval_seconds: int) -> bool:
    if redis is None:
        return True
    now = time.time()
    try:
        raw = await redis.get(HELPDESK_LAST_ATTEMPT_KEY)
        previous = _float_or_none(raw)
        if previous is not None and now - previous < interval_seconds:
            return False
        await redis.set(
            HELPDESK_LAST_ATTEMPT_KEY,
            str(now),
            ex=max(interval_seconds * 2, 300),
        )
    except Exception as exc:
        logger.warning(
            "helpdesk_imap_throttle_unavailable",
            extra={"error_type": type(exc).__name__},
        )
        return True
    return True


async def _claim_lock(redis: RedisLike | None, interval_seconds: int) -> bool:
    if redis is None:
        return True
    try:
        claimed = await redis.set(
            HELPDESK_LOCK_KEY,
            "1",
            ex=max(interval_seconds, 60),
            nx=True,
        )
    except Exception as exc:
        logger.warning(
            "helpdesk_imap_lock_unavailable",
            extra={"error_type": type(exc).__name__},
        )
        return True
    return bool(claimed)


def _float_or_none(value: object) -> float | None:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="ignore")
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()
