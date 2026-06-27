from app.services.helpdesk_imap.formatter import build_helpdesk_ticket_card
from app.services.helpdesk_imap.parser import ParsedHelpdeskTicket


def test_helpdesk_formatter_escapes_html_and_creates_open_button() -> None:
    ticket = ParsedHelpdeskTicket(
        ticket_id="0047513",
        event_type="new_ticket",
        ticket_url="https://sd.asdf.help/index.php?redirect=ticket_47513&noAUTO=1",
        title="<script>alert(1)</script>",
        employee_full_name="Масленникова <Дарья>",
        position="удаленный специалист",
        manager="Васильев & Ко",
        start_date="30.06.2026 (понедельник)",
        access_items=["почта <cofi.ru>", "Доступ в AMO CRM"],
        comment_count=0,
        task_count=0,
        sender_name=None,
        sender_email_masked="s***d@asdf.help",
        raw_excerpt="",
        parse_status="parsed",
    )

    card = build_helpdesk_ticket_card(ticket)

    assert "<b>Заявка GLPI #0047513</b>" in card.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in card.text
    assert "Масленникова &lt;Дарья&gt;" in card.text
    assert "Васильев &amp; Ко" in card.text
    assert "□ почта &lt;cofi.ru&gt;" in card.text
    assert "<script>" not in card.text
    assert "**" not in card.text
    assert card.reply_markup is not None
    assert card.reply_markup.inline_keyboard[0][0].text == "Открыть заявку"
    assert (
        card.reply_markup.inline_keyboard[0][0].url
        == "https://sd.asdf.help/index.php?redirect=ticket_47513&noAUTO=1"
    )


def test_helpdesk_formatter_omits_invalid_url_button() -> None:
    ticket = ParsedHelpdeskTicket(
        ticket_id="0047513",
        event_type="new_ticket",
        ticket_url="file:///etc/passwd",
        title="Тема",
        employee_full_name=None,
        position=None,
        manager=None,
        start_date=None,
        access_items=[],
        comment_count=None,
        task_count=None,
        sender_name=None,
        sender_email_masked=None,
        raw_excerpt="",
        parse_status="parsed",
    )

    card = build_helpdesk_ticket_card(ticket)

    assert card.reply_markup is None


def test_helpdesk_formatter_clips_long_text() -> None:
    ticket = ParsedHelpdeskTicket(
        ticket_id="0047513",
        event_type="new_ticket",
        ticket_url=None,
        title="Очень длинная тема " * 500,
        employee_full_name=None,
        position=None,
        manager=None,
        start_date=None,
        access_items=[f"доступ {index}" for index in range(30)],
        comment_count=None,
        task_count=None,
        sender_name=None,
        sender_email_masked=None,
        raw_excerpt="",
        parse_status="parsed",
    )

    card = build_helpdesk_ticket_card(ticket)

    assert len(card.text) <= 4096
    assert card.text.endswith("…") or "доступ 1" in card.text
