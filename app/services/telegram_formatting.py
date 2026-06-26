from __future__ import annotations

from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

from app.services.reminder_service import ReminderView
from app.services.shopping_service import ShoppingListView

TELEGRAM_HTML_LIMIT = 4096
DEFAULT_TIMEZONE = ZoneInfo("Europe/Moscow")


def format_shopping_list_html(view: ShoppingListView) -> str:
    lines = ["<b>🛒 Список покупок</b>", ""]
    if not view.active and not view.done:
        lines.append("Список пуст.")
        return _truncate("\n".join(lines))
    if view.active:
        lines.append("<b>Активные:</b>")
        lines.extend(
            f"{index}. ☐ {escape(item.text)}" for index, item in enumerate(view.active, start=1)
        )
    if view.done:
        if view.active:
            lines.append("")
        lines.append("<b>Куплено:</b>")
        lines.extend(f"✅ <s>{escape(item.text)}</s>" for item in view.done)
    return _truncate("\n".join(lines))


def format_reminder_created_html(
    reminder: ReminderView,
    *,
    now: datetime | None = None,
    timezone: ZoneInfo = DEFAULT_TIMEZONE,
) -> str:
    when = escape(format_reminder_time(reminder.remind_at, now=now, timezone=timezone))
    return _truncate(
        "<b>⏰ Напоминание создано</b>\n\n"
        f"<blockquote>{escape(reminder.text)}</blockquote>\n"
        f"Когда: <b>{when}</b>"
    )


def format_reminder_due_html(reminder: ReminderView) -> str:
    return _truncate(
        "<b>⏰ Напоминание</b>\n\n"
        f"<blockquote>{escape(reminder.text)}</blockquote>"
    )


def format_reminders_html(
    reminders: list[ReminderView],
    *,
    now: datetime | None = None,
    timezone: ZoneInfo = DEFAULT_TIMEZONE,
) -> str:
    lines = ["<b>⏰ Активные напоминания</b>", ""]
    if not reminders:
        lines.append("Активных напоминаний нет.")
        return "\n".join(lines)
    for index, reminder in enumerate(reminders, start=1):
        when = escape(format_reminder_time(reminder.remind_at, now=now, timezone=timezone))
        lines.append(f"{index}. <b>{when}</b> — {escape(reminder.text)}")
    return _truncate("\n".join(lines))


def format_reminder_time(
    value: datetime,
    *,
    now: datetime | None = None,
    timezone: ZoneInfo = DEFAULT_TIMEZONE,
) -> str:
    local_value = (
        value.astimezone(timezone)
        if value.tzinfo is not None
        else value.replace(tzinfo=timezone)
    )
    current = now or datetime.now(timezone)
    current = (
        current.astimezone(timezone)
        if current.tzinfo is not None
        else current.replace(tzinfo=timezone)
    )
    if local_value.date() == current.date():
        prefix = "сегодня"
    elif local_value.date() == current.date().fromordinal(current.date().toordinal() + 1):
        prefix = "завтра"
    else:
        prefix = local_value.strftime("%d.%m")
    return f"{prefix}, {local_value:%H:%M}"


def _truncate(text: str) -> str:
    if len(text) <= TELEGRAM_HTML_LIMIT:
        return text
    return text[: TELEGRAM_HTML_LIMIT - 1] + "…"
