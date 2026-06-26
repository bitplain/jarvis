from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.simple_intent_parser import (
    ReminderCreateIntent,
    ReminderListIntent,
    ShoppingAddIntent,
    ShoppingDeleteIntent,
    ShoppingListIntent,
    parse_explicit_intent,
    sanitize_shopping_items_input,
    split_shopping_items,
)

MSK = ZoneInfo("Europe/Moscow")


def test_parse_shopping_add_single_item() -> None:
    intent = parse_explicit_intent("добавь хлеб в список покупок")

    assert isinstance(intent, ShoppingAddIntent)
    assert intent.items == ["хлеб"]


def test_parse_shopping_add_multiple_items_by_comma() -> None:
    intent = parse_explicit_intent("добавь молоко, яйца, сыр в список")

    assert isinstance(intent, ShoppingAddIntent)
    assert intent.items == ["молоко", "яйца", "сыр"]


def test_split_shopping_items_by_simple_russian_connector() -> None:
    assert split_shopping_items("мазик и молоко") == ["мазик", "молоко"]
    assert split_shopping_items("хлеб, молоко и яйца") == ["хлеб", "молоко", "яйца"]


def test_sanitize_shopping_items_input_strips_current_bot_mention() -> None:
    assert (
        sanitize_shopping_items_input("@Home_ai_my_bot творожок", "Home_ai_my_bot")
        == "творожок"
    )
    assert (
        sanitize_shopping_items_input("@home_ai_my_bot творожок", "Home_ai_my_bot")
        == "творожок"
    )
    assert (
        sanitize_shopping_items_input("@other_bot творожок", "Home_ai_my_bot")
        == "@other_bot творожок"
    )


def test_parse_shopping_add_strips_current_bot_mention() -> None:
    intent = parse_explicit_intent(
        "добавь @Home_ai_my_bot творожок в список",
        bot_username="Home_ai_my_bot",
    )

    assert isinstance(intent, ShoppingAddIntent)
    assert intent.items == ["творожок"]


def test_parse_buy_colon_shopping_add_splits_plain_words() -> None:
    intent = parse_explicit_intent("Купить: хлеб сок мазик запеканку")

    assert isinstance(intent, ShoppingAddIntent)
    assert intent.items == ["хлеб", "сок", "мазик", "запеканку"]


def test_parse_buy_colon_shopping_add_reuses_existing_splitters() -> None:
    intent = parse_explicit_intent("купить: хлеб, сок и молоко")

    assert isinstance(intent, ShoppingAddIntent)
    assert intent.items == ["хлеб", "сок", "молоко"]


def test_parse_buy_colon_shopping_add_strips_current_bot_mention() -> None:
    intent = parse_explicit_intent(
        "@Home_ai_my_bot купить: творожок",
        bot_username="Home_ai_my_bot",
    )

    assert isinstance(intent, ShoppingAddIntent)
    assert intent.items == ["творожок"]


def test_parse_buy_colon_does_not_overbroaden_natural_language() -> None:
    assert parse_explicit_intent("где купить молоко?") is None
    assert parse_explicit_intent("можешь купить молоко?") is None
    assert isinstance(parse_explicit_intent("что купить?"), ShoppingListIntent)


def test_parse_shopping_show_and_delete() -> None:
    assert isinstance(parse_explicit_intent("что купить?"), ShoppingListIntent)
    assert isinstance(parse_explicit_intent("список"), ShoppingListIntent)

    intent = parse_explicit_intent("удали молоко из списка")

    assert isinstance(intent, ShoppingDeleteIntent)
    assert intent.query == "молоко"


def test_parse_reminder_relative_minutes_and_hours() -> None:
    now = datetime(2026, 6, 26, 12, 0, tzinfo=MSK)

    minutes = parse_explicit_intent("напомни через 30 минут проверить духовку", now=now)
    hours = parse_explicit_intent("напомни через 2 часа проверить доставку", now=now)

    assert isinstance(minutes, ReminderCreateIntent)
    assert minutes.text == "проверить духовку"
    assert minutes.remind_at == datetime(2026, 6, 26, 12, 30, tzinfo=MSK)
    assert isinstance(hours, ReminderCreateIntent)
    assert hours.remind_at == datetime(2026, 6, 26, 14, 0, tzinfo=MSK)


def test_parse_reminder_tomorrow_and_absolute_date() -> None:
    now = datetime(2026, 6, 26, 12, 0, tzinfo=MSK)

    tomorrow = parse_explicit_intent("напомни завтра в 10 купить молоко", now=now)
    absolute = parse_explicit_intent("напомни 28.06 в 14:00 оплатить счёт", now=now)

    assert isinstance(tomorrow, ReminderCreateIntent)
    assert tomorrow.remind_at == datetime(2026, 6, 27, 10, 0, tzinfo=MSK)
    assert tomorrow.text == "купить молоко"
    assert isinstance(absolute, ReminderCreateIntent)
    assert absolute.remind_at == datetime(2026, 6, 28, 14, 0, tzinfo=MSK)
    assert absolute.text == "оплатить счёт"


def test_parse_reminder_list_invalid_and_ambiguous() -> None:
    assert isinstance(parse_explicit_intent("покажи напоминания"), ReminderListIntent)
    assert parse_explicit_intent("напомни когда-нибудь купить молоко") is not None
    assert parse_explicit_intent("обычный разговор про хлеб и молоко") is None


def test_parse_help_triggers() -> None:
    assert parse_explicit_intent("помощь список") is not None
    assert parse_explicit_intent("помощь напоминания") is not None
    assert parse_explicit_intent("как пользоваться списком") is not None
    assert parse_explicit_intent("как пользоваться напоминаниями") is not None


def test_parse_reminder_uses_custom_timezone_for_tomorrow() -> None:
    amsterdam = ZoneInfo("Europe/Amsterdam")
    now = datetime(2026, 6, 26, 23, 30, tzinfo=amsterdam)

    intent = parse_explicit_intent(
        "напомни завтра в 10 купить молоко",
        now=now,
        timezone=amsterdam,
    )

    assert isinstance(intent, ReminderCreateIntent)
    assert intent.remind_at == datetime(2026, 6, 27, 10, 0, tzinfo=amsterdam)
