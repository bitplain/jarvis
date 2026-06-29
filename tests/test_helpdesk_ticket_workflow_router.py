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
        self.fail_next_answer = False

    async def answer(self, text: str, **kwargs: Any) -> None:
        if self.fail_next_answer:
            self.fail_next_answer = False
            raise RuntimeError("telegram unavailable")
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


class FakeVacationService:
    def __init__(self) -> None:
        self.enabled = False
        self.review_marked = 0
        self.items: list[Any] = []

    async def enable(self, *, actor_user_id: int) -> object:
        self.enabled = True
        return type(
            "VacationState",
            (),
            {"enabled": True, "enabled_at": NOW, "last_reviewed_at": None},
        )()

    async def disable(self, *, actor_user_id: int) -> object:
        self.enabled = False
        return type(
            "VacationState",
            (),
            {"enabled": False, "enabled_at": NOW, "disabled_at": NOW},
        )()

    async def summary(self, *, telegram_chat_id: int) -> object:
        del telegram_chat_id
        return type(
            "VacationSummary",
            (),
            {
                "enabled": self.enabled,
                "enabled_at": NOW if self.enabled else None,
                "disabled_at": None if self.enabled else NOW,
                "last_reviewed_at": None,
                "events_since_start": len(self.items),
                "events_since_last_review": len(self.items),
            },
        )()

    async def review_items(self, *, telegram_chat_id: int) -> list[Any]:
        del telegram_chat_id
        return list(self.items)

    async def mark_reviewed(self) -> object:
        self.review_marked += 1
        return object()


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


def test_router_registers_helpdesk_ticket_and_vacation_commands() -> None:
    assert helpdesk_tickets.HELPDESK_TICKET_COMMANDS == (
        "ticket",
        "helpdesk_vacation",
        "helpdesk_vacation_on",
        "helpdesk_vacation_off",
    )


@pytest.mark.asyncio
async def test_helpdesk_vacation_commands_are_access_gated() -> None:
    service = FakeVacationService()
    message = FakeMessage("/helpdesk_vacation_on", user_id=7)

    await helpdesk_tickets.cmd_helpdesk_vacation_on(
        message,  # type: ignore[arg-type]
        settings=Settings(admin_telegram_ids="100500"),
        helpdesk_vacation_service=service,
    )

    assert message.answers == [{"text": "Доступ запрещён."}]
    assert service.enabled is False


@pytest.mark.asyncio
async def test_helpdesk_vacation_on_off_and_status_commands() -> None:
    service = FakeVacationService()
    settings = Settings(
        admin_telegram_ids="100500",
        helpdesk_telegram_chat_id="-100123",
        helpdesk_imap_enabled=True,
        helpdesk_imap_host="imap.example.ru",
        helpdesk_imap_username="support@example.ru",
        helpdesk_imap_password="real-password",
    )
    on_message = FakeMessage("/helpdesk_vacation_on", chat_id=100500)
    status_message = FakeMessage("/helpdesk_vacation", chat_id=100500)
    off_message = FakeMessage("/helpdesk_vacation_off", chat_id=100500)

    await helpdesk_tickets.cmd_helpdesk_vacation_on(
        on_message,  # type: ignore[arg-type]
        settings=settings,
        helpdesk_vacation_service=service,
    )
    await helpdesk_tickets.cmd_helpdesk_vacation(
        status_message,  # type: ignore[arg-type]
        settings=settings,
        helpdesk_vacation_service=service,
    )
    await helpdesk_tickets.cmd_helpdesk_vacation_off(
        off_message,  # type: ignore[arg-type]
        settings=settings,
        helpdesk_vacation_service=service,
        helpdesk_ticket_service=HelpdeskTicketWorkflowService(
            InMemoryHelpdeskTicketWorkItemRepository(),
            now_factory=lambda: NOW,
        ),
    )

    assert "Режим отпуска включён." in on_message.answers[0]["text"]
    assert "Vacation mode: on" in status_message.answers[0]["text"]
    assert "Показать новые за отпуск" in [
        button.text
        for row in status_message.answers[0]["reply_markup"].inline_keyboard
        for button in row
    ]
    assert "Режим отпуска выключен." in off_message.answers[0]["text"]


@pytest.mark.asyncio
async def test_helpdesk_vacation_review_updates_cursor_only_after_successful_send() -> None:
    service = FakeVacationService()
    service.enabled = True
    repository = InMemoryHelpdeskTicketWorkItemRepository()
    workflow = HelpdeskTicketWorkflowService(repository, now_factory=lambda: NOW)
    item = await workflow.create_or_update_waiting_ack(
        glpi_ticket_id="0047513",
        latest_event_id=None,
        title="Выход <нового> сотрудника",
        telegram_chat_id=-100123,
    )
    service.items = [
        type(
            "VacationReviewItem",
            (),
            {
                "glpi_ticket_id": "0047513",
                "title": "Выход <нового> сотрудника",
                "event_type": "new_ticket",
                "events_count": 1,
                "work_item_id": item.id,
                "work_item_status": "waiting_ack",
            },
        )()
    ]
    failing_message = FakeMessage("/helpdesk_vacation", chat_id=100500)
    failing_message.fail_next_answer = True

    with pytest.raises(RuntimeError):
        await helpdesk_tickets.show_helpdesk_vacation_review(
            failing_message,  # type: ignore[arg-type]
            settings=Settings(
                admin_telegram_ids="100500",
                helpdesk_telegram_chat_id="-100123",
            ),
            helpdesk_vacation_service=service,
        )
    assert service.review_marked == 0

    ok_message = FakeMessage("/helpdesk_vacation", chat_id=100500)
    await helpdesk_tickets.show_helpdesk_vacation_review(
        ok_message,  # type: ignore[arg-type]
        settings=Settings(
            admin_telegram_ids="100500",
            helpdesk_telegram_chat_id="-100123",
        ),
        helpdesk_vacation_service=service,
    )

    assert service.review_marked == 1
    assert "Новые заявки за отпуск" in ok_message.answers[0]["text"]
    assert "Выход &lt;нового&gt; сотрудника" in ok_message.answers[0]["text"]
