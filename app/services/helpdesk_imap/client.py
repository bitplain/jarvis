from __future__ import annotations

import asyncio
import imaplib
from dataclasses import dataclass
from datetime import datetime
from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
from typing import Any

from app.services.helpdesk_imap.config import HelpdeskImapConfig
from app.services.helpdesk_imap.parser import decode_mime_header, extract_text_from_email_message


class HelpdeskImapError(RuntimeError):
    error_code = "imap"


class HelpdeskImapAuthError(HelpdeskImapError):
    error_code = "auth"


class HelpdeskImapNetworkError(HelpdeskImapError):
    error_code = "network"


@dataclass(frozen=True)
class HelpdeskFetchedEmail:
    folder: str
    uid: str | None
    message_id: str | None
    subject: str
    from_header: str
    received_at: datetime | None
    body: str


class HelpdeskImapClient:
    def __init__(self, config: HelpdeskImapConfig) -> None:
        self.config = config
        self._connection: Any | None = None

    async def fetch_recent(self) -> list[HelpdeskFetchedEmail]:
        return await asyncio.to_thread(self._fetch_recent_sync)

    async def mark_seen(self, *, folder: str, uid: str) -> None:
        del folder
        await asyncio.to_thread(self._mark_seen_sync, uid)

    async def close(self) -> None:
        await asyncio.to_thread(self._close_sync)

    def _connect(self) -> Any:
        if self._connection is not None:
            return self._connection
        try:
            connection = (
                imaplib.IMAP4_SSL(self.config.host, self.config.port)
                if self.config.ssl
                else imaplib.IMAP4(self.config.host, self.config.port)
            )
            connection.login(self.config.username, self.config.password)
            connection.select(self.config.folder, readonly=not self.config.mark_seen)
        except imaplib.IMAP4.error as exc:
            raise HelpdeskImapAuthError("imap_auth_failed") from exc
        except OSError as exc:
            raise HelpdeskImapNetworkError("imap_network_failed") from exc
        self._connection = connection
        return connection

    def _fetch_recent_sync(self) -> list[HelpdeskFetchedEmail]:
        connection = self._connect()
        try:
            status, data = connection.uid("search", None, "UNSEEN")
        except imaplib.IMAP4.error as exc:
            raise HelpdeskImapNetworkError("imap_search_failed") from exc
        if status != "OK" or not data:
            return []
        raw_uids = data[0] or b""
        if isinstance(raw_uids, str):
            raw_uids = raw_uids.encode()
        uids = [uid.decode("ascii", errors="ignore") for uid in raw_uids.split()]
        messages: list[HelpdeskFetchedEmail] = []
        for uid in uids[-50:]:
            fetched = self._fetch_uid(connection, uid)
            if fetched is not None:
                messages.append(fetched)
        return messages

    def _fetch_uid(self, connection: Any, uid: str) -> HelpdeskFetchedEmail | None:
        try:
            status, data = connection.uid("fetch", uid, "(BODY.PEEK[])")
        except imaplib.IMAP4.error as exc:
            raise HelpdeskImapNetworkError("imap_fetch_failed") from exc
        if status != "OK":
            return None
        raw = _extract_raw_email(data)
        if raw is None:
            return None
        message = BytesParser(policy=policy.default).parsebytes(raw)
        return HelpdeskFetchedEmail(
            folder=self.config.folder,
            uid=uid,
            message_id=_header(message, "Message-ID") or None,
            subject=_header(message, "Subject"),
            from_header=_header(message, "From"),
            received_at=_parse_date(_header(message, "Date")),
            body=extract_text_from_email_message(raw),
        )

    def _mark_seen_sync(self, uid: str) -> None:
        connection = self._connect()
        try:
            connection.uid("store", uid, "+FLAGS", "(\\Seen)")
        except imaplib.IMAP4.error as exc:
            raise HelpdeskImapNetworkError("imap_mark_seen_failed") from exc

    def _close_sync(self) -> None:
        connection = self._connection
        self._connection = None
        if connection is None:
            return
        try:
            connection.close()
        except imaplib.IMAP4.error:
            pass
        try:
            connection.logout()
        except imaplib.IMAP4.error:
            pass


def _extract_raw_email(data: object) -> bytes | None:
    if not isinstance(data, list | tuple):
        return None
    for item in data:
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], bytes):
            return item[1]
    return None


def _header(message: Any, name: str) -> str:
    value = message.get(name)
    return decode_mime_header(str(value)) if value is not None else ""


def _parse_date(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
