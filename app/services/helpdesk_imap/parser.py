from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from email import policy
from email.header import decode_header
from email.parser import BytesParser
from email.utils import parseaddr
from html import unescape
from typing import Any, cast

from app.services.helpdesk_imap.config import mask_email, mask_email_addresses


@dataclass(frozen=True)
class ParsedHelpdeskTicket:
    ticket_id: str | None = None
    event_type: str = "unknown"
    ticket_url: str | None = None
    title: str | None = None
    description: str | None = None
    employee_full_name: str | None = None
    position: str | None = None
    manager: str | None = None
    start_date: str | None = None
    access_items: list[str] | None = None
    comment_count: int | None = None
    task_count: int | None = None
    sender_name: str | None = None
    sender_email_masked: str | None = None
    raw_excerpt: str = ""
    parse_status: str = "failed"

    @property
    def safe_access_items(self) -> list[str]:
        return self.access_items or []


def parse_glpi_email(
    *,
    subject: str,
    body: str,
    from_header: str,
) -> ParsedHelpdeskTicket:
    decoded_subject = decode_mime_header(subject).strip()
    text = _normalize_text(body)
    sender_name, sender_email = parseaddr(from_header)
    ticket_id = _match_first(r"\[GLPI\s*#([0-9]+)\]", decoded_subject)
    event_type = _event_type(decoded_subject, text)
    ticket_url = _match_first(r"(?im)^\s*URL\s*:\s*(https?://\S+)\s*$", text)
    title = _section_after_label(text, "Заголовок", ["Описание", "Заявка"])
    if not title:
        title = _strip_glpi_prefix(decoded_subject) or decoded_subject or None
    description = _section_after_label(text, "Описание", ["Настроить доступы"])
    comment_count = _int_or_none(_match_first(r"(?im)^Количество комментариев:\s*(\d+)", text))
    task_count = _int_or_none(_match_first(r"(?im)^Число задач:\s*(\d+)", text))
    employee_full_name = _line_value(text, "ФИО")
    position = _line_value(text, "Должность")
    manager = _line_value(text, "Руководитель")
    start_date = _line_value(text, "Предварительная дата выхода")
    access_items = _access_items(text)
    parse_status = (
        "parsed"
        if any(
            [
                ticket_id,
                ticket_url,
                employee_full_name,
                position,
                manager,
                access_items,
                event_type != "unknown",
            ]
        )
        else "failed"
    )
    return ParsedHelpdeskTicket(
        ticket_id=ticket_id,
        event_type=event_type,
        ticket_url=ticket_url,
        title=title,
        description=description,
        employee_full_name=employee_full_name,
        position=position,
        manager=manager,
        start_date=start_date,
        access_items=access_items,
        comment_count=comment_count,
        task_count=task_count,
        sender_name=sender_name or None,
        sender_email_masked=mask_email(sender_email) if sender_email else None,
        raw_excerpt=_raw_excerpt(text),
        parse_status=parse_status,
    )


def extract_text_from_email_message(raw: bytes) -> str:
    message = BytesParser(policy=policy.default).parsebytes(raw)
    plain_parts: list[str] = []
    html_parts: list[str] = []
    parts: Iterable[Any] = message.walk() if message.is_multipart() else [message]
    for part in parts:
        content_type = part.get_content_type()
        if content_type not in {"text/plain", "text/html"}:
            continue
        payload = cast(bytes | None, part.get_payload(decode=True))
        if payload is None:
            continue
        charset = part.get_content_charset() or "utf-8"
        text = payload.decode(charset, errors="replace")
        if content_type == "text/plain":
            plain_parts.append(text)
        else:
            html_parts.append(_html_to_text(text))
    if plain_parts:
        return _normalize_text("\n".join(plain_parts))
    return _normalize_text("\n".join(html_parts))


def decode_mime_header(value: str | None) -> str:
    if not value:
        return ""
    parts: list[str] = []
    for part, encoding in decode_header(value):
        if isinstance(part, bytes):
            parts.append(part.decode(encoding or "utf-8", errors="replace"))
        else:
            parts.append(part)
    return "".join(parts)


def _normalize_text(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n").strip()


def _html_to_text(value: str) -> str:
    text = re.sub(r"(?i)<br\s*/?>", "\n", value)
    text = re.sub(r"(?i)</p\s*>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return unescape(text)


def _match_first(pattern: str, value: str) -> str | None:
    match = re.search(pattern, value)
    if not match:
        return None
    return match.group(1).strip()


def _event_type(subject: str, body: str) -> str:
    haystack = f"{subject}\n{body}".lower()
    if "новая заявка" in haystack:
        return "new_ticket"
    if "новый комментарий" in haystack:
        return "comment"
    return "unknown"


def _strip_glpi_prefix(subject: str) -> str:
    without_ticket = re.sub(r"^\s*\[GLPI\s*#[0-9]+\]\s*", "", subject).strip()
    without_event = re.sub(r"^(Новая заявка|Новый комментарий)\s*", "", without_ticket).strip()
    return without_event


def _section_after_label(text: str, label: str, stop_labels: list[str]) -> str | None:
    pattern = re.compile(rf"(?im)^\s*{re.escape(label)}\s*:\s*(.*)$")
    match = pattern.search(text)
    if not match:
        return None
    first_line = match.group(1).strip()
    tail = text[match.end() :].splitlines()
    lines: list[str] = []
    if first_line:
        lines.append(first_line)
    stop_pattern = re.compile(
        r"^\s*(?:" + "|".join(re.escape(stop) for stop in stop_labels) + r")\s*:",
        re.I,
    )
    for line in tail:
        stripped = line.strip()
        if stop_pattern.match(stripped):
            break
        if stripped or lines:
            lines.append(stripped)
    section = "\n".join(line for line in lines if line).strip()
    return section or None


def _line_value(text: str, label: str) -> str | None:
    return _match_first(rf"(?im)^\s*{re.escape(label)}\s*:\s*(.+?)\s*$", text)


def _access_items(text: str) -> list[str]:
    match = re.search(r"(?im)^\s*Настроить доступы\s*:\s*$", text)
    if not match:
        return []
    items: list[str] = []
    for line in text[match.end() :].splitlines():
        stripped = line.strip()
        if not stripped:
            if items:
                break
            continue
        if re.match(r"(?i)^(From|Sent|To|Cc|Subject|Заголовок|Описание|ФИО|Должность):", stripped):
            break
        item = re.sub(r"^\s*(?:\d+[\).]|[-*•□])\s*", "", stripped).strip()
        if item:
            items.append(item)
    return items


def _raw_excerpt(text: str) -> str:
    compact = re.sub(r"\s+", " ", mask_email_addresses(text)).strip()
    if len(compact) <= 500:
        return compact
    return compact[:499] + "…"


def _int_or_none(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None
