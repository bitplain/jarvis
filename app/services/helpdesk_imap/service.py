from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parseaddr
from typing import Protocol

from aiogram import Bot

from app.services.helpdesk_imap.client import (
    HelpdeskFetchedEmail,
    HelpdeskImapAuthError,
    HelpdeskImapNetworkError,
    HelpdeskMailboxSnapshot,
)
from app.services.helpdesk_imap.config import HelpdeskImapConfig
from app.services.helpdesk_imap.formatter import build_helpdesk_ticket_card
from app.services.helpdesk_imap.parser import ParsedHelpdeskTicket, parse_glpi_email
from app.services.helpdesk_ticket_workflow import WAITING_ACK, StoredHelpdeskTicketWorkItem

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

    async def failed_notification_event_id(
        self,
        *,
        folder: str,
        imap_uid: str | None,
        message_id: str | None,
    ) -> str | None: ...

    async def create_event(self, **values: object) -> str | None: ...

    async def mark_notified(
        self,
        event_id: str,
        *,
        telegram_chat_id: int,
        telegram_message_id: int,
    ) -> None: ...

    async def mark_notify_failed(self, event_id: str, *, error_code: str) -> None: ...


class HelpdeskMailboxState(Protocol):
    folder: str
    uidvalidity: str | None
    last_seen_uid: int | None


class HelpdeskMailboxStateRepository(Protocol):
    async def get_state(self, *, folder: str) -> HelpdeskMailboxState | None: ...

    async def upsert_state(
        self,
        *,
        folder: str,
        uidvalidity: str | None,
        last_seen_uid: int | None,
        baseline: bool = False,
        last_error_code: str | None = None,
    ) -> HelpdeskMailboxState: ...


class HelpdeskClient(Protocol):
    async def fetch_recent(self) -> list[HelpdeskFetchedEmail]: ...

    async def mailbox_snapshot(self) -> HelpdeskMailboxSnapshot: ...

    async def fetch_since(self, last_seen_uid: int) -> list[HelpdeskFetchedEmail]: ...

    async def mark_seen(self, *, folder: str, uid: str) -> None: ...

    async def close(self) -> None: ...


class HelpdeskNotifier(Protocol):
    async def send_ticket(
        self,
        *,
        chat_id: int,
        ticket: ParsedHelpdeskTicket,
        work_item_id: str | None = None,
    ) -> int: ...


class HelpdeskTicketWorkRepository(Protocol):
    async def upsert_waiting_ack(
        self,
        *,
        glpi_ticket_id: str,
        latest_event_id: str | None,
        title: str,
        telegram_chat_id: int,
        now: datetime,
    ) -> StoredHelpdeskTicketWorkItem: ...


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
    last_seen_uid: int | None = None


class TelegramHelpdeskNotifier:
    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    async def send_ticket(
        self,
        *,
        chat_id: int,
        ticket: ParsedHelpdeskTicket,
        work_item_id: str | None = None,
    ) -> int:
        card = build_helpdesk_ticket_card(ticket, work_item_id=work_item_id)
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
        state_repository: HelpdeskMailboxStateRepository,
        client: HelpdeskClient,
        notifier: HelpdeskNotifier,
        redis: RedisLike | None = None,
        ticket_work_repository: HelpdeskTicketWorkRepository | None = None,
    ) -> None:
        self.config = config
        self.repository = repository
        self.state_repository = state_repository
        self.client = client
        self.notifier = notifier
        self.redis = redis
        self.ticket_work_repository = ticket_work_repository

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
        current_last_seen_uid: int | None = None
        halted_on_delivery_failure = False
        try:
            snapshot = await self.client.mailbox_snapshot()
            state = await self.state_repository.get_state(folder=self.config.folder)
            if state is None:
                baseline_uid = snapshot.max_uid or 0
                await self.state_repository.upsert_state(
                    folder=self.config.folder,
                    uidvalidity=snapshot.uidvalidity,
                    last_seen_uid=baseline_uid,
                    baseline=True,
                )
                await record_helpdesk_status(self.redis, success=True, last_error=last_error)
                return HelpdeskRunResult(status="baseline_set", last_seen_uid=baseline_uid)
            if (
                state.uidvalidity is not None
                and snapshot.uidvalidity is not None
                and state.uidvalidity != snapshot.uidvalidity
            ):
                baseline_uid = snapshot.max_uid or 0
                logger.warning(
                    "helpdesk_imap_uidvalidity_changed",
                    extra={"folder": self.config.folder},
                )
                await self.state_repository.upsert_state(
                    folder=self.config.folder,
                    uidvalidity=snapshot.uidvalidity,
                    last_seen_uid=baseline_uid,
                    baseline=True,
                )
                await record_helpdesk_status(self.redis, success=True, last_error=last_error)
                return HelpdeskRunResult(status="baseline_reset", last_seen_uid=baseline_uid)
            current_last_seen_uid = state.last_seen_uid or 0
            messages = await self.client.fetch_since(current_last_seen_uid)
            for message in messages:
                message_uid = _uid_int(message.uid)
                if message_uid is not None and message_uid <= current_last_seen_uid:
                    skipped_duplicates += 1
                    continue
                if not self._candidate_matches(message):
                    skipped_filtered += 1
                    current_last_seen_uid = _max_uid(current_last_seen_uid, message_uid)
                    continue
                failed_event_id = await self.repository.failed_notification_event_id(
                    folder=message.folder,
                    imap_uid=message.uid,
                    message_id=message.message_id,
                )
                if failed_event_id is not None:
                    result = await self._retry_failed_notification(message, failed_event_id)
                    processed += result.processed
                    failed += result.failed
                    if result.error_code is not None:
                        last_error = result.error_code
                    if result.error_code == "telegram":
                        halted_on_delivery_failure = True
                        break
                    current_last_seen_uid = _max_uid(current_last_seen_uid, message_uid)
                    continue
                if await self.repository.exists(
                    folder=message.folder,
                    imap_uid=message.uid,
                    message_id=message.message_id,
                ):
                    skipped_duplicates += 1
                    current_last_seen_uid = _max_uid(current_last_seen_uid, message_uid)
                    continue
                result = await self._process_message(message)
                processed += result.processed
                failed += result.failed
                if result.error_code is not None:
                    last_error = result.error_code
                if result.error_code == "telegram":
                    halted_on_delivery_failure = True
                    break
                current_last_seen_uid = _max_uid(current_last_seen_uid, message_uid)
            if not halted_on_delivery_failure:
                current_last_seen_uid = _max_uid(current_last_seen_uid, snapshot.max_uid)
            await self.state_repository.upsert_state(
                folder=self.config.folder,
                uidvalidity=snapshot.uidvalidity,
                last_seen_uid=current_last_seen_uid,
                baseline=False,
                last_error_code=None if last_error == "none" else last_error,
            )
            await record_helpdesk_status(self.redis, success=True, last_error=last_error)
        except HelpdeskImapAuthError:
            await self._record_state_error("auth")
            await record_helpdesk_status(self.redis, last_error="auth")
            logger.warning("helpdesk_imap_auth_failed", extra=self.config.safe_summary())
            return HelpdeskRunResult(status="failed", error_code="auth")
        except HelpdeskImapNetworkError:
            await self._record_state_error("network")
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
            last_seen_uid=current_last_seen_uid,
        )

    async def baseline_now(self) -> HelpdeskRunResult:
        if not self.config.enabled or not self.config.configured:
            return HelpdeskRunResult(status="config_incomplete", error_code="config")
        try:
            snapshot = await self.client.mailbox_snapshot()
            baseline_uid = snapshot.max_uid or 0
            await self.state_repository.upsert_state(
                folder=self.config.folder,
                uidvalidity=snapshot.uidvalidity,
                last_seen_uid=baseline_uid,
                baseline=True,
            )
            await record_helpdesk_status(self.redis, success=True, last_error="none")
            return HelpdeskRunResult(status="baseline_set", last_seen_uid=baseline_uid)
        except HelpdeskImapAuthError:
            await self._record_state_error("auth")
            await record_helpdesk_status(self.redis, last_error="auth")
            logger.warning("helpdesk_imap_auth_failed", extra=self.config.safe_summary())
            return HelpdeskRunResult(status="failed", error_code="auth")
        except HelpdeskImapNetworkError:
            await self._record_state_error("network")
            await record_helpdesk_status(self.redis, last_error="network")
            logger.warning("helpdesk_imap_network_failed", extra=self.config.safe_summary())
            return HelpdeskRunResult(status="failed", error_code="network")
        finally:
            await self.client.close()

    async def _record_state_error(self, error_code: str) -> None:
        try:
            state = await self.state_repository.get_state(folder=self.config.folder)
            await self.state_repository.upsert_state(
                folder=self.config.folder,
                uidvalidity=getattr(state, "uidvalidity", None),
                last_seen_uid=getattr(state, "last_seen_uid", None),
                baseline=False,
                last_error_code=error_code,
            )
        except Exception as exc:
            logger.warning(
                "helpdesk_imap_state_error_store_failed",
                extra={"error_type": type(exc).__name__},
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
        return await self._notify_ticket(event_id, message, ticket)

    async def _retry_failed_notification(
        self,
        message: HelpdeskFetchedEmail,
        event_id: str,
    ) -> HelpdeskRunResult:
        ticket = parse_glpi_email(
            subject=message.subject,
            body=message.body,
            from_header=message.from_header,
        )
        if ticket.parse_status != "parsed":
            await self.repository.mark_notify_failed(event_id, error_code="parse")
            return HelpdeskRunResult(
                status="parse_failed",
                processed=1,
                failed=1,
                error_code="parse",
            )
        return await self._notify_ticket(event_id, message, ticket)

    async def _notify_ticket(
        self,
        event_id: str,
        message: HelpdeskFetchedEmail,
        ticket: ParsedHelpdeskTicket,
    ) -> HelpdeskRunResult:
        assert self.config.telegram_chat_id is not None
        work_item_id = await self._ensure_work_item_id(event_id, message, ticket)
        try:
            message_id = await self.notifier.send_ticket(
                chat_id=self.config.telegram_chat_id,
                ticket=ticket,
                work_item_id=work_item_id,
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

    async def _ensure_work_item_id(
        self,
        event_id: str,
        message: HelpdeskFetchedEmail,
        ticket: ParsedHelpdeskTicket,
    ) -> str | None:
        if (
            self.ticket_work_repository is None
            or ticket.event_type != "new_ticket"
            or not ticket.ticket_id
        ):
            return None
        try:
            item = await self.ticket_work_repository.upsert_waiting_ack(
                glpi_ticket_id=ticket.ticket_id,
                latest_event_id=event_id,
                title=ticket.title or message.subject,
                telegram_chat_id=self.config.telegram_chat_id or 0,
                now=_utcnow(),
            )
        except Exception as exc:
            logger.warning(
                "helpdesk_ticket_work_item_upsert_failed",
                extra={"error_type": type(exc).__name__},
            )
            return None
        return item.id if item.status == WAITING_ACK else None


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


def _uid_int(value: str | None) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _max_uid(current: int, candidate: int | None) -> int:
    if candidate is None:
        return current
    return max(current, candidate)


def _now_iso() -> str:
    return _utcnow().isoformat()


def _utcnow() -> datetime:
    return datetime.now(UTC)
