from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

DEFAULT_TIMEZONE = ZoneInfo("Europe/Moscow")


@dataclass(frozen=True)
class ShoppingAddIntent:
    items: list[str]


@dataclass(frozen=True)
class ShoppingListIntent:
    pass


@dataclass(frozen=True)
class ShoppingDeleteIntent:
    query: str


@dataclass(frozen=True)
class ShoppingClearDoneIntent:
    pass


@dataclass(frozen=True)
class ReminderCreateIntent:
    text: str
    remind_at: datetime


@dataclass(frozen=True)
class ReminderListIntent:
    pass


@dataclass(frozen=True)
class ParserHelpIntent:
    topic: str


ExplicitIntent = (
    ShoppingAddIntent
    | ShoppingListIntent
    | ShoppingDeleteIntent
    | ShoppingClearDoneIntent
    | ReminderCreateIntent
    | ReminderListIntent
    | ParserHelpIntent
)


def parse_explicit_intent(
    text: str,
    *,
    now: datetime | None = None,
    timezone: ZoneInfo = DEFAULT_TIMEZONE,
) -> ExplicitIntent | None:
    normalized = _normalize_text(text)
    if not normalized:
        return None
    shopping = _parse_shopping(normalized)
    if shopping is not None:
        return shopping
    return _parse_reminder(normalized, now=now, timezone=timezone)


def _parse_shopping(text: str) -> ExplicitIntent | None:
    if text in {"покажи список покупок", "список покупок", "что купить?"}:
        return ShoppingListIntent()
    if text == "очисти купленное":
        return ShoppingClearDoneIntent()
    delete_match = re.match(r"^удали\s+(.+?)\s+из\s+списка(?:\s+покупок)?$", text)
    if delete_match:
        query = _clean_item(delete_match.group(1))
        return ShoppingDeleteIntent(query) if query else ParserHelpIntent("shopping")
    add_match = re.match(r"^добавь\s+(.+?)\s+в\s+список(?:\s+покупок)?$", text)
    if add_match:
        items = _split_items(add_match.group(1))
        return ShoppingAddIntent(items) if items else ParserHelpIntent("shopping")
    buy_match = re.match(r"^купи\s+(.+)$", text)
    if buy_match:
        items = _split_items(buy_match.group(1))
        return ShoppingAddIntent(items) if items else ParserHelpIntent("shopping")
    return None


def _parse_reminder(
    text: str,
    *,
    now: datetime | None,
    timezone: ZoneInfo,
) -> ExplicitIntent | None:
    if text in {"покажи напоминания", "напоминания", "мои напоминания"}:
        return ReminderListIntent()
    if not text.startswith("напомни "):
        return None
    current = now or datetime.now(timezone)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone)
    current = current.astimezone(timezone)
    body = text.removeprefix("напомни ").strip()
    relative_match = re.match(
        r"^через\s+(\d{1,3})\s+(минут(?:у|ы)?|час(?:а|ов)?)\s+(.+)$",
        body,
    )
    if relative_match:
        amount = int(relative_match.group(1))
        unit = relative_match.group(2)
        reminder_text = _normalize_text(relative_match.group(3))
        if not reminder_text:
            return ParserHelpIntent("reminder")
        delta = timedelta(minutes=amount) if unit.startswith("минут") else timedelta(hours=amount)
        return ReminderCreateIntent(text=reminder_text[:500], remind_at=current + delta)
    day_match = re.match(r"^(сегодня|завтра)\s+в\s+(\d{1,2})(?::(\d{2}))?\s+(.+)$", body)
    if day_match:
        day_word = day_match.group(1)
        hour = int(day_match.group(2))
        minute = int(day_match.group(3) or "0")
        reminder_text = _normalize_text(day_match.group(4))
        if not _valid_time(hour, minute) or not reminder_text:
            return ParserHelpIntent("reminder")
        target_date = current.date()
        if day_word == "завтра":
            target_date += timedelta(days=1)
        remind_at = datetime.combine(
            target_date,
            datetime.min.time(),
            tzinfo=timezone,
        ).replace(hour=hour, minute=minute)
        if remind_at <= current:
            return ParserHelpIntent("reminder")
        return ReminderCreateIntent(text=reminder_text[:500], remind_at=remind_at)
    date_match = re.match(r"^(\d{1,2})\.(\d{1,2})\s+в\s+(\d{1,2})(?::(\d{2}))?\s+(.+)$", body)
    if date_match:
        day = int(date_match.group(1))
        month = int(date_match.group(2))
        hour = int(date_match.group(3))
        minute = int(date_match.group(4) or "0")
        reminder_text = _normalize_text(date_match.group(5))
        if not _valid_time(hour, minute) or not reminder_text:
            return ParserHelpIntent("reminder")
        try:
            remind_at = datetime(current.year, month, day, hour, minute, tzinfo=timezone)
        except ValueError:
            return ParserHelpIntent("reminder")
        if remind_at <= current:
            try:
                remind_at = datetime(current.year + 1, month, day, hour, minute, tzinfo=timezone)
            except ValueError:
                return ParserHelpIntent("reminder")
        return ReminderCreateIntent(text=reminder_text[:500], remind_at=remind_at)
    return ParserHelpIntent("reminder")


def _split_items(text: str) -> list[str]:
    if "," in text or "\n" in text:
        raw_items = re.split(r"[,\n]+", text)
    elif re.search(r"\s+и\s+", text) and len(text.split()) <= 7:
        raw_items = re.split(r"\s+и\s+", text)
    else:
        raw_items = [text]
    return [_clean_item(item) for item in raw_items if _clean_item(item)][:20]


def _clean_item(text: str) -> str:
    return _normalize_text(text)[:120]


def _normalize_text(text: str) -> str:
    return " ".join(text.strip().lower().split())


def _valid_time(hour: int, minute: int) -> bool:
    return 0 <= hour <= 23 and 0 <= minute <= 59
