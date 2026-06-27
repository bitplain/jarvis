from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from html import escape
from zoneinfo import ZoneInfo

from app.services.daily_brief_service import DailyBriefView
from app.services.reminder_service import ReminderView
from app.services.shopping_service import ShoppingItemView, ShoppingListView

TELEGRAM_HTML_LIMIT = 4096
DEFAULT_TIMEZONE = ZoneInfo("Europe/Moscow")


def format_shopping_list_html(view: ShoppingListView) -> str:
    lines = ["<b>🛒 Список покупок</b>", ""]
    if not view.active and not view.done:
        lines.append("Список пуст.")
        return _truncate("\n".join(lines))
    if view.active:
        grouped = _group_shopping_items(view.active)
        if any(item.category for item in view.active):
            index = 1
            for category, items in grouped:
                lines.append(f"<b>{_category_icon(category)} {escape(category)}</b>")
                for item in items:
                    lines.append(f"{index}. ☐ {_format_shopping_item_detail(item)}")
                    index += 1
                lines.append("")
            if lines[-1] == "":
                lines.pop()
        else:
            lines.append("<b>Активные:</b>")
            lines.extend(
                f"{index}. ☐ {_format_shopping_item_detail(item)}"
                for index, item in enumerate(view.active, start=1)
            )
    if view.done:
        if view.active:
            lines.append("")
        lines.append("<b>Куплено:</b>")
        lines.extend(f"✅ <s>{_format_shopping_item_detail(item)}</s>" for item in view.done)
    return _truncate("\n".join(lines))


def format_daily_brief_html(brief: DailyBriefView) -> str:
    lines = ["<b>📋 Сводка дня</b>", ""]
    if brief.today_reminders:
        lines.append("<b>⏰ Сегодня:</b>")
        for index, reminder in enumerate(brief.today_reminders, start=1):
            when = reminder.remind_at.astimezone(brief.timezone).strftime("%H:%M")
            lines.append(f"{index}. {escape(when)} — {escape(reminder.text)}")
        lines.append("")
    else:
        lines.extend(["<b>⏰ Сегодня:</b>", "Напоминаний на сегодня нет.", ""])
    if brief.overdue_reminders:
        lines.append("<b>⚠️ Просрочено:</b>")
        for index, reminder in enumerate(brief.overdue_reminders, start=1):
            lines.append(
                f"{index}. {escape(_brief_reminder_time(reminder, brief))} — "
                f"{escape(reminder.text)}"
            )
        lines.append("")
    lines.append("<b>🛒 Покупки:</b>")
    if brief.shopping_items:
        lines.extend(f"- {_format_shopping_item_detail(item)}" for item in brief.shopping_items)
    else:
        lines.append("Список пуст.")
    lines.append("")
    lines.append("<b>🧠 Память:</b>")
    if brief.memory_texts:
        lines.extend(f"- {escape(text)}" for text in brief.memory_texts)
    else:
        lines.append("Нет сохранённых заметок.")
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


def format_lists_reminders_private_help_html() -> str:
    return (
        "<b>Что я умею со списками и напоминаниями:</b>\n\n"
        "<b>Список покупок:</b>\n"
        "• добавь хлеб в список покупок\n"
        "• добавь молоко, яйца и сыр в список\n"
        "• покажи список покупок\n"
        "• удали молоко из списка\n\n"
        "<b>Напоминания:</b>\n"
        "• напомни через 30 минут проверить духовку\n"
        "• напомни завтра в 10 купить молоко\n"
        "• напомни 28.06 в 14:00 оплатить счёт\n"
        "• покажи напоминания"
    )


def format_lists_reminders_group_help_html(bot_username: str) -> str:
    username = escape(bot_username.strip().lstrip("@") or "bot_username")
    mention = f"@{username}"
    return (
        "<b>В группе обращайтесь ко мне явно:</b>\n"
        f"{mention} добавь хлеб, молоко и яйца в список покупок\n"
        f"{mention} покажи список покупок\n"
        f"{mention} напомни завтра в 9 купить памперсы"
    )


def format_reminder_due_html(
    reminder: ReminderView,
    *,
    now: datetime | None = None,
    timezone: ZoneInfo = DEFAULT_TIMEZONE,
) -> str:
    when = escape(format_reminder_time(reminder.remind_at, now=now, timezone=timezone))
    return _truncate(
        "<b>⏰ Напоминание</b>\n\n"
        f"<blockquote>{escape(reminder.text)}</blockquote>\n"
        f"Когда: <b>{when}</b>"
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


def _group_shopping_items(
    items: list[ShoppingItemView],
) -> list[tuple[str, list[ShoppingItemView]]]:
    order = ["Молочка", "Хлеб", "Ребёнок", "Мясо", "Овощи", "Фрукты", "Другое"]
    grouped: dict[str, list[ShoppingItemView]] = {}
    for item in items:
        grouped.setdefault(item.category or "Другое", []).append(item)
    return [(category, grouped[category]) for category in order if category in grouped] + [
        (category, values) for category, values in grouped.items() if category not in order
    ]


def _category_icon(category: str) -> str:
    return {
        "Молочка": "🥛",
        "Хлеб": "🍞",
        "Ребёнок": "👶",
        "Мясо": "🥩",
        "Овощи": "🥕",
        "Фрукты": "🍎",
        "Другое": "📦",
    }.get(category, "📦")


def _format_shopping_item_detail(item: ShoppingItemView) -> str:
    details = []
    if item.quantity is not None:
        quantity = _format_quantity(item.quantity)
        details.append(f"{quantity} {escape(item.unit or '')}".strip())
    if item.note:
        details.append(escape(item.note))
    suffix = f" — {', '.join(details)}" if details else ""
    return f"{escape(item.text)}{suffix}"


def _format_quantity(value: Decimal | int) -> str:
    normalized = Decimal(value).normalize()
    if normalized == normalized.to_integral():
        return str(normalized.quantize(Decimal("1")))
    return format(normalized, "f")


def _brief_reminder_time(reminder: ReminderView, brief: DailyBriefView) -> str:
    local_value = reminder.remind_at.astimezone(brief.timezone)
    if local_value.date().toordinal() == brief.now.date().toordinal() - 1:
        return f"вчера {local_value:%H:%M}"
    return local_value.strftime("%d.%m %H:%M")


def _truncate(text: str) -> str:
    if len(text) <= TELEGRAM_HTML_LIMIT:
        return text
    return text[: TELEGRAM_HTML_LIMIT - 1] + "…"
