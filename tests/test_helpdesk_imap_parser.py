from email.header import Header

from app.services.helpdesk_imap.parser import (
    decode_mime_header,
    extract_text_from_email_message,
    parse_glpi_email,
)

GLPI_NEW_TICKET_BODY = """
===== Чтобы ответить по email, пишите выше этой линии =====
URL : http://sd.asdf.help/index.php?redirect=ticket_47513&noAUTO=1
Количество комментариев: 0
Число задач: 0
Заявка: Описание
Заголовок:
RE: Выход нового сотрудника: Масленникова Д.А. - специалист колл-центра
Описание:
From: HR <hr@example.ru>
Sent: Friday, June 26, 2026 11:00
To: Service Desk
Subject: RE: Выход нового сотрудника

Добрый день!
Просьба оформить рабочее место новому сотруднику.
ФИО: Масленникова Дарья Александровна
Должность: удаленный специалист колл-центра
Руководитель: Васильев С.
Предварительная дата выхода: 30.06.2026 (понедельник)

Настроить доступы:
1. почта с доменом cofi.ru
2. Доступ в AMO CRM
3. Телефония Манго, Билайн
"""


def test_parse_glpi_new_ticket_email_extracts_helpdesk_fields() -> None:
    parsed = parse_glpi_email(
        subject="[GLPI #0047513] Новая заявка RE: Выход нового сотрудника",
        body=GLPI_NEW_TICKET_BODY,
        from_header="Service Desk <sd@asdf.help>",
    )

    assert parsed.ticket_id == "0047513"
    assert parsed.event_type == "new_ticket"
    assert parsed.ticket_url == "http://sd.asdf.help/index.php?redirect=ticket_47513&noAUTO=1"
    assert parsed.title == "RE: Выход нового сотрудника: Масленникова Д.А. - специалист колл-центра"
    assert parsed.employee_full_name == "Масленникова Дарья Александровна"
    assert parsed.position == "удаленный специалист колл-центра"
    assert parsed.manager == "Васильев С."
    assert parsed.start_date == "30.06.2026 (понедельник)"
    assert parsed.access_items == [
        "почта с доменом cofi.ru",
        "Доступ в AMO CRM",
        "Телефония Манго, Билайн",
    ]
    assert parsed.comment_count == 0
    assert parsed.task_count == 0
    assert parsed.sender_email_masked == "s***d@asdf.help"
    assert "hr@example.ru" not in parsed.raw_excerpt


def test_parse_glpi_comment_email_subject() -> None:
    parsed = parse_glpi_email(
        subject="[GLPI #0047513] Новый комментарий RE: Выход нового сотрудника",
        body="URL : https://sd.asdf.help/ticket/47513\nОписание:\nКомментарий",
        from_header="sd@asdf.help",
    )

    assert parsed.ticket_id == "0047513"
    assert parsed.event_type == "comment"
    assert parsed.ticket_url == "https://sd.asdf.help/ticket/47513"


def test_parse_glpi_email_missing_fields_does_not_crash() -> None:
    parsed = parse_glpi_email(subject="Plain subject", body="без структуры", from_header="")

    assert parsed.ticket_id is None
    assert parsed.event_type == "unknown"
    assert parsed.title == "Plain subject"
    assert parsed.access_items == []
    assert parsed.parse_status == "failed"


def test_extract_text_from_html_email_message() -> None:
    raw = (
        b"Content-Type: text/html; charset=utf-8\r\n"
        b"Subject: [GLPI #1]\r\n"
        b"\r\n"
        + "<html><body><p>ФИО: &lt;script&gt;</p><br>Должность: инженер</body></html>".encode()
    )

    text = extract_text_from_email_message(raw)

    assert "ФИО: <script>" in text
    assert "Должность: инженер" in text
    assert "<html>" not in text


def test_decode_mime_header_decodes_weird_encoding_subject() -> None:
    encoded = Header("[GLPI #0047513] Новая заявка", "utf-8").encode()

    assert decode_mime_header(encoded) == "[GLPI #0047513] Новая заявка"
