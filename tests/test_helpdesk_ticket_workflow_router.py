from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.bot.routers import helpdesk_tickets
from app.core.config import Settings
from app.services.helpdesk_ticket_workflow import (
    HelpdeskTicketWorkflowService,
    InMemoryHelpdeskTicketWorkItemRepository,
)

NOW = datetime(2026, 6, 29, 9, 0, tzinfo=UTC)


class FakeUser:
    def __init__(self, user_id: int | None) -> None:
        self.id = user_id


class FakeChat:
    def __init__(self, chat_id: int, chat_type: str = "private") -> None:
        self.id = chat_id
        self.type = chat_type


class FakeMessage:
    def __init__(
        self,
        text: str = "/ticket",
        *,
        user_id: int | None = 100500,
        chat_id: int = 100500,
        chat_type: str = "private",
    ) -> None:
        self.text = text
        self.caption = None
        self.from_user = FakeUser(user_id) if user_id is not None else None
        self.chat = FakeChat(chat_id, chat_type)
        self.answers: list[dict[str, Any]] = []
        self.edits: list[dict[str, Any]] = []

    async def answer(self, text: str, **kwargs: Any) -> None:
        self.answers.append({"text": text, **kwargs})

    async def edit_text(self, text: str, **kwargs: Any) -> None:
        self.edits.append({"text": text, **kwargs})


class FakeCallbackQuery:
    def __init__(
        self,
        data: str,
        *,
        user_id: int | None = 100500,
        chat_id: int = -100123,
        chat_type: str = "supergroup",
    ) -> None:
        self.data = data
        self.from_user = FakeUser(user_id) if user_id is not None else None
        self.message = FakeMessage(
            user_id=user_id,
            chat_id=chat_id,
            chat_type=chat_type,
        )
        self.answers: list[dict[str, Any]] = []

    async def answer(self, text: str | None = None, **kwargs: Any) -> None:
        self.answers.append({"text": text, **kwargs})


@pytest.mark.asyncio
async def test_ticket_command_shows_in_work_tickets_and_escapes_html() -> None:
    service = HelpdeskTicketWorkflowService(
        InMemoryHelpdeskTicketWorkItemRepository(),
        now_factory=lambda: NOW,
    )
    item = await service.create_or_update_waiting_ack(
        glpi_ticket_id="0047513",
        latest_event_id=None,
        title="Выход <нового> сотрудника",
        telegram_chat_id=-100123,
    )
    await service.take(item.id, actor_user_id=100500, telegram_chat_id=-100123)
    message = FakeMessage(chat_id=100500)

    await helpdesk_tickets.cmd_ticket(
        message,  # type: ignore[arg-type]
        settings=Settings(
            admin_telegram_ids="100500",
            helpdesk_telegram_chat_id="-100123",
        ),
        helpdesk_ticket_service=service,
    )

    rendered = message.answers[0]["text"]
    assert "Заявки в работе" in rendered
    assert "GLPI #0047513" in rendered
    assert "Выход &lt;нового&gt; сотрудника" in rendered
    assert "<нового>" not in rendered
    button_texts = [
        button.text
        for row in message.answers[0]["reply_markup"].inline_keyboard
        for button in row
    ]
    assert button_texts == ["Готово", "Отложить 1ч"]


@pytest.mark.asyncio
async def test_ticket_command_empty_state() -> None:
    service = HelpdeskTicketWorkflowService(
        InMemoryHelpdeskTicketWorkItemRepository(),
        now_factory=lambda: NOW,
    )
    message = FakeMessage(chat_id=100500)

    await helpdesk_tickets.cmd_ticket(
        message,  # type: ignore[arg-type]
        settings=Settings(admin_telegram_ids="100500"),
        helpdesk_ticket_service=service,
    )

    assert message.answers == [{"text": "Заявок в работе нет.", "parse_mode": "HTML"}]


@pytest.mark.asyncio
async def test_ticket_callbacks_are_access_gated() -> None:
    service = HelpdeskTicketWorkflowService(
        InMemoryHelpdeskTicketWorkItemRepository(),
        now_factory=lambda: NOW,
    )
    item = await service.create_or_update_waiting_ack(
        glpi_ticket_id="0047513",
        latest_event_id=None,
        title="Выход нового сотрудника",
        telegram_chat_id=-100123,
    )
    callback = FakeCallbackQuery(f"hd_ticket:take:{item.id}", user_id=7)

    await helpdesk_tickets.handle_helpdesk_ticket_callback(
        callback,  # type: ignore[arg-type]
        settings=Settings(admin_telegram_ids="100500"),
        helpdesk_ticket_service=service,
    )

    assert callback.answers == [{"text": "Доступ запрещён.", "show_alert": True}]
    assert service.repository.items[item.id].status == "waiting_ack"


@pytest.mark.asyncio
async def test_take_done_and_snooze_callbacks_update_ticket() -> None:
    service = HelpdeskTicketWorkflowService(
        InMemoryHelpdeskTicketWorkItemRepository(),
        now_factory=lambda: NOW,
    )
    item = await service.create_or_update_waiting_ack(
        glpi_ticket_id="0047513",
        latest_event_id=None,
        title="Выход нового сотрудника",
        telegram_chat_id=-100123,
    )

    take = FakeCallbackQuery(f"hd_ticket:take:{item.id}")
    snooze = FakeCallbackQuery(f"hd_ticket:snooze:{item.id}:60")
    done = FakeCallbackQuery(f"hd_ticket:done:{item.id}")
    settings = Settings(admin_telegram_ids="100500")
    await helpdesk_tickets.handle_helpdesk_ticket_callback(
        take,  # type: ignore[arg-type]
        settings=settings,
        helpdesk_ticket_service=service,
    )
    await helpdesk_tickets.handle_helpdesk_ticket_callback(
        snooze,  # type: ignore[arg-type]
        settings=settings,
        helpdesk_ticket_service=service,
    )
    assert service.repository.items[item.id].next_reminder_at == NOW + timedelta(hours=1)
    await helpdesk_tickets.handle_helpdesk_ticket_callback(
        done,  # type: ignore[arg-type]
        settings=settings,
        helpdesk_ticket_service=service,
    )

    assert "взята в работу" in take.message.edits[0]["text"]
    assert "отложена на 1 час" in snooze.message.edits[0]["text"]
    assert "закрыта" in done.message.edits[0]["text"]
    assert service.repository.items[item.id].status == "done"


@pytest.mark.asyncio
async def test_private_admin_ticket_callback_uses_configured_helpdesk_chat() -> None:
    service = HelpdeskTicketWorkflowService(
        InMemoryHelpdeskTicketWorkItemRepository(),
        now_factory=lambda: NOW,
    )
    item = await service.create_or_update_waiting_ack(
        glpi_ticket_id="0047513",
        latest_event_id=None,
        title="Выход нового сотрудника",
        telegram_chat_id=-100123,
    )
    callback = FakeCallbackQuery(
        f"hd_ticket:take:{item.id}",
        chat_id=100500,
        chat_type="private",
    )

    await helpdesk_tickets.handle_helpdesk_ticket_callback(
        callback,  # type: ignore[arg-type]
        settings=Settings(
            admin_telegram_ids="100500",
            helpdesk_telegram_chat_id="-100123",
        ),
        helpdesk_ticket_service=service,
    )

    assert service.repository.items[item.id].status == "in_work"
    assert "взята в работу" in callback.message.edits[0]["text"]


def test_router_registers_only_ticket_command() -> None:
    assert helpdesk_tickets.HELPDESK_TICKET_COMMANDS == ("ticket",)
