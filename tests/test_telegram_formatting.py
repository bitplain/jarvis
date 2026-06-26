from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.reminder_service import ReminderView
from app.services.shopping_service import ShoppingItemView, ShoppingListView
from app.services.telegram_formatting import (
    TELEGRAM_HTML_LIMIT,
    format_reminder_created_html,
    format_reminder_due_html,
    format_reminders_html,
    format_shopping_list_html,
)

MSK = ZoneInfo("Europe/Moscow")


def test_format_shopping_list_escapes_user_text_and_renders_statuses() -> None:
    view = ShoppingListView(
        scope_type="private",
        scope_chat_id=100500,
        title="Список покупок",
        active=[
            ShoppingItemView(id="a1", text="<script>", status="active"),
            ShoppingItemView(id="a2", text="milk & bread", status="active"),
        ],
        done=[ShoppingItemView(id="d1", text='сыр "особый"', status="done")],
    )

    html = format_shopping_list_html(view)

    assert "<b>🛒 Список покупок</b>" in html
    assert "&lt;script&gt;" in html
    assert "milk &amp; bread" in html
    assert "сыр &quot;особый&quot;" in html
    assert "<script>" not in html
    assert "<s>сыр" in html


def test_format_empty_shopping_list() -> None:
    html = format_shopping_list_html(
        ShoppingListView(
            scope_type="group",
            scope_chat_id=-100123,
            title="Список покупок",
            active=[],
            done=[],
        )
    )

    assert html == "<b>🛒 Список покупок</b>\n\nСписок пуст."


def test_format_reminders_escape_text_and_stay_within_limit() -> None:
    reminder = ReminderView(
        id="r1",
        scope_type="private",
        chat_id=100500,
        user_id=100500,
        text="<script> milk & bread",
        remind_at=datetime(2026, 6, 27, 10, 0, tzinfo=MSK),
        status="scheduled",
    )

    created = format_reminder_created_html(reminder, now=datetime(2026, 6, 26, 12, 0, tzinfo=MSK))
    due = format_reminder_due_html(reminder)
    listing = format_reminders_html([reminder], now=datetime(2026, 6, 26, 12, 0, tzinfo=MSK))

    assert "&lt;script&gt; milk &amp; bread" in created
    assert "&lt;script&gt; milk &amp; bread" in due
    assert "&lt;script&gt; milk &amp; bread" in listing
    assert "<script>" not in created + due + listing
    assert "Когда: <b>завтра, 10:00</b>" in created
    assert len(created) <= TELEGRAM_HTML_LIMIT
