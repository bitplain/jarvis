from __future__ import annotations

from dataclasses import dataclass
from html import escape

from aiogram.types import InlineKeyboardMarkup

from app.services.helpdesk_imap.parser import ParsedHelpdeskTicket
from app.services.helpdesk_ticket_workflow import build_waiting_ack_keyboard

TELEGRAM_HTML_LIMIT = 4096


@dataclass(frozen=True)
class HelpdeskTicketCard:
    text: str
    reply_markup: InlineKeyboardMarkup | None


def build_helpdesk_ticket_card(
    ticket: ParsedHelpdeskTicket,
    *,
    work_item_id: str | None = None,
) -> HelpdeskTicketCard:
    ticket_number = ticket.ticket_id or "unknown"
    icon = "💬" if ticket.event_type == "comment" else "🆕"
    lines = [f"{icon} <b>Заявка GLPI #{escape(ticket_number)}</b>", ""]
    if ticket.title:
        lines.extend(["<b>Тема:</b>", escape(_clip(ticket.title, 700)), ""])
    if ticket.employee_full_name:
        lines.extend(["<b>Сотрудник:</b>", escape(_clip(ticket.employee_full_name, 240)), ""])
    if ticket.position:
        lines.extend(["<b>Должность:</b>", escape(_clip(ticket.position, 240)), ""])
    if ticket.manager:
        lines.extend(["<b>Руководитель:</b>", escape(_clip(ticket.manager, 240)), ""])
    if ticket.start_date:
        lines.extend(["<b>Дата выхода:</b>", escape(_clip(ticket.start_date, 160)), ""])
    if ticket.safe_access_items:
        lines.append("<b>Нужно настроить:</b>")
        for item in ticket.safe_access_items[:10]:
            lines.append(f"□ {escape(_clip(item, 240))}")
        if len(ticket.safe_access_items) > 10:
            lines.append("□ …")
        lines.append("")
    if ticket.event_type == "comment":
        lines.extend(["<b>Событие:</b>", "Новый комментарий", ""])
    lines.extend(["<b>Источник:</b>", "HelpDesk email"])
    text = "\n".join(lines).strip()
    if len(text) > TELEGRAM_HTML_LIMIT:
        text = text[: TELEGRAM_HTML_LIMIT - 1] + "…"
    reply_markup = build_waiting_ack_keyboard(work_item_id) if work_item_id else None
    return HelpdeskTicketCard(text=text, reply_markup=reply_markup)


def _clip(value: str, limit: int) -> str:
    clean = value.strip()
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1] + "…"
