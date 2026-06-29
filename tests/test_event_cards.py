import re

from app.services.event_cards import (
    build_event_callback_data,
    render_card_buttons,
    render_card_to_telegram_text,
)
from app.services.telegram_formatting import TELEGRAM_HTML_LIMIT


def _assert_safe_telegram_html(html: str) -> None:
    assert len(html) <= TELEGRAM_HTML_LIMIT
    assert html.count("<b>") == html.count("</b>")
    assert html.rfind("<") <= html.rfind(">")
    assert html.rfind("&") <= html.rfind(";")
    assert not re.search(r"<[^>]*$", html)
    assert not re.search(r"&(?:#[0-9]*|#x[0-9a-fA-F]*|[a-zA-Z][a-zA-Z0-9]*)?$", html)


def test_render_card_to_telegram_text_escapes_fields_and_facts() -> None:
    html = render_card_to_telegram_text(
        {
            "type": "reminder",
            "title": "Напоминание <важно>",
            "severity": "info",
            "facts": [
                {"label": "Когда", "value": "Сегодня & завтра"},
                {"label": "<Источник>", "value": "Jarvis"},
            ],
            "summary": "Проверить <окно> & закрыть дверь",
            "actions": [
                {"id": "done", "label": "Готово"},
                {"id": "snooze", "label": "Позже"},
            ],
        }
    )

    assert "<b>Напоминание &lt;важно&gt;</b>" in html
    assert "Когда: <b>Сегодня &amp; завтра</b>" in html
    assert "&lt;Источник&gt;: <b>Jarvis</b>" in html
    assert "Проверить &lt;окно&gt; &amp; закрыть дверь" in html
    assert "<важно>" not in html
    assert "<окно>" not in html
    assert '"actions"' not in html


def test_render_card_long_title_caps_html_without_breaking_tags_or_escaping() -> None:
    long_title = "Очень длинный заголовок <script> & \"quote\" " * 300

    html = render_card_to_telegram_text(
        {
            "type": "reminder",
            "title": long_title,
            "severity": "info",
            "facts": [],
            "summary": "",
            "actions": [{"id": "details", "label": "Подробнее"}],
        }
    )

    _assert_safe_telegram_html(html)
    assert "&lt;script&gt;" in html
    assert "&amp;" in html
    assert "&quot;quote&quot;" in html
    assert "<script>" not in html
    assert '"actions"' not in html
    assert "{" not in html
    assert "}" not in html


def test_render_card_long_fallback_title_and_body_caps_html_safely() -> None:
    html = render_card_to_telegram_text(
        {"type": ["broken"], "facts": "not-a-list"},
        fallback_title="Событие <script> & \"quote\" " * 300,
        fallback_body="Очень длинное тело <body> & " * 300,
    )

    _assert_safe_telegram_html(html)
    assert "&lt;script&gt;" in html
    assert "&amp;" in html
    assert "&quot;quote&quot;" in html
    assert "<script>" not in html
    assert "<body>" not in html
    assert "not-a-list" not in html
    assert "{" not in html
    assert "}" not in html


def test_render_card_long_facts_cap_html_without_breaking_bold_tags() -> None:
    long_fact = "Очень длинный факт <fact> & " * 300

    html = render_card_to_telegram_text(
        {
            "type": "reminder",
            "title": "Короткая карточка",
            "severity": "info",
            "facts": [{"label": "Подробность <label>", "value": long_fact}],
            "summary": "",
            "actions": [{"id": "details", "label": "Подробнее"}],
        },
        fallback_title="Длинное событие",
        fallback_body="Очень длинное тело <body> & " * 300,
    )

    _assert_safe_telegram_html(html)
    assert "&lt;label&gt;" in html
    assert "<fact>" not in html
    assert "{" not in html
    assert "}" not in html
    assert '"facts"' not in html


def test_render_card_long_summary_does_not_end_with_cut_html_entity() -> None:
    prefix = "<b>Сводка</b>\n\n"
    filler_len = TELEGRAM_HTML_LIMIT - 2 - len(prefix)
    long_summary = ("x" * filler_len) + "& <script> tail"

    html = render_card_to_telegram_text(
        {
            "type": "note",
            "title": "Сводка",
            "severity": "info",
            "facts": [],
            "summary": long_summary,
            "actions": [],
        }
    )

    _assert_safe_telegram_html(html)
    assert "<script>" not in html
    assert "&…" not in html


def test_render_card_fallback_caps_long_body_and_keeps_escaping() -> None:
    html = render_card_to_telegram_text(
        {"type": ["broken"], "facts": "not-a-list"},
        fallback_title="Событие <fallback>",
        fallback_body="Очень длинное тело <body> & " * 300,
    )

    _assert_safe_telegram_html(html)
    assert "&lt;fallback&gt;" in html
    assert "&lt;body&gt;" in html
    assert "<fallback>" not in html
    assert "<body>" not in html
    assert "not-a-list" not in html
    assert "{" not in html
    assert "}" not in html


def test_render_card_fallback_never_prints_raw_json() -> None:
    html = render_card_to_telegram_text(
        {"type": ["broken"], "facts": "not-a-list"},
        fallback_title="Событие",
        fallback_body="Карточка временно недоступна.",
    )

    assert "<b>Событие</b>" in html
    assert "Карточка временно недоступна." in html
    assert "not-a-list" not in html
    assert "{" not in html
    assert "}" not in html


def test_render_card_buttons_builds_stable_safe_callback_data() -> None:
    event_id = "0123456789abcdef0123456789abcdef"
    markup = render_card_buttons(
        event_id,
        {
            "type": "reminder",
            "title": "Напоминание",
            "severity": "info",
            "facts": [],
            "summary": "Текст",
            "actions": [
                {"id": "done", "label": "Готово"},
                {"id": "snooze", "label": "Позже"},
                {"id": "details", "label": "Подробнее"},
                {"id": "bad:action", "label": "Нельзя"},
            ],
        },
    )

    assert markup is not None
    buttons = [button for row in markup.inline_keyboard for button in row]
    assert [button.text for button in buttons] == ["Готово", "Позже", "Подробнее"]
    assert [button.callback_data for button in buttons] == [
        f"event:done:{event_id}",
        f"event:snooze:{event_id}",
        f"event:details:{event_id}",
    ]
    assert build_event_callback_data("done", event_id) == f"event:done:{event_id}"


def test_render_card_buttons_returns_none_for_empty_or_broken_actions() -> None:
    assert render_card_buttons("0123456789abcdef0123456789abcdef", None) is None
    assert (
        render_card_buttons(
            "0123456789abcdef0123456789abcdef",
            {"actions": [{"id": "bad:action", "label": "Нельзя"}]},
        )
        is None
    )
