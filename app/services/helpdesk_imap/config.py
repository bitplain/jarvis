from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.core.config import Settings


@dataclass(frozen=True)
class HelpdeskImapConfig:
    enabled: bool
    host: str
    port: int
    ssl: bool
    username: str = field(repr=False)
    password: str = field(repr=False)
    folder: str
    poll_interval_seconds: int
    from_filter: str
    subject_prefix: str
    telegram_chat_id_raw: str = field(repr=False)
    telegram_chat_id: int | None
    mark_seen: bool

    @classmethod
    def from_settings(cls, settings: Settings) -> HelpdeskImapConfig:
        chat_id_raw = str(settings.helpdesk_telegram_chat_id).strip()
        return cls(
            enabled=settings.helpdesk_imap_enabled,
            host=settings.helpdesk_imap_host.strip(),
            port=settings.helpdesk_imap_port,
            ssl=settings.helpdesk_imap_ssl,
            username=settings.helpdesk_imap_username.strip(),
            password=settings.helpdesk_imap_password,
            folder=settings.helpdesk_imap_folder.strip() or "INBOX",
            poll_interval_seconds=settings.helpdesk_imap_poll_interval_seconds,
            from_filter=settings.helpdesk_imap_from_filter.strip(),
            subject_prefix=settings.helpdesk_imap_subject_prefix.strip(),
            telegram_chat_id_raw=chat_id_raw,
            telegram_chat_id=_parse_chat_id(chat_id_raw),
            mark_seen=settings.helpdesk_mark_seen,
        )

    @property
    def safe_username(self) -> str:
        return mask_email(self.username)

    @property
    def missing_required(self) -> tuple[str, ...]:
        if not self.enabled:
            return ()
        missing: list[str] = []
        if not self.host:
            missing.append("helpdesk_imap_host")
        if not self.username:
            missing.append("helpdesk_imap_username")
        if not self.password:
            missing.append("helpdesk_imap_password")
        if self.telegram_chat_id is None:
            missing.append("helpdesk_telegram_chat_id")
        return tuple(missing)

    @property
    def configured(self) -> bool:
        return self.enabled and not self.missing_required

    def safe_summary(self) -> dict[str, str]:
        return {
            "enabled": _yes_no(self.enabled),
            "configured": _yes_no(self.configured),
            "host": "configured" if self.host else "missing",
            "username": self.safe_username,
            "folder": self.folder or "INBOX",
            "mark_seen": _yes_no(self.mark_seen),
        }


def mask_email(value: str | None) -> str:
    text = (value or "").strip()
    if not text:
        return "missing"
    if "@" not in text:
        return _mask_local_part(text)
    local, domain = text.split("@", 1)
    return f"{_mask_local_part(local)}@{domain}"


def mask_email_addresses(value: str) -> str:
    return re.sub(
        r"[\w.!#$%&'*+/=?^`{|}~-]+@[\w.-]+\.[A-Za-z]{2,}",
        lambda match: mask_email(match.group(0)),
        value,
    )


def _mask_local_part(value: str) -> str:
    if not value:
        return "***"
    if len(value) == 1:
        return f"{value}***"
    return f"{value[0]}***{value[-1]}"


def _parse_chat_id(value: str) -> int | None:
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"
