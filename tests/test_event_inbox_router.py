from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.routers import event_inbox
from app.core.config import Settings
from app.db.models import EventItem, EventPriority, EventScope, EventStatus, EventType
from app.services.event_cards import build_event_callback_data
from app.services.event_items import EventItemCreate, EventItemService

NOW = datetime(2026, 6, 29, 6, 50, tzinfo=UTC)


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
        text: str,
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

    async def answer(self, text: str, **kwargs: Any) -> None:
        self.answers.append({"text": text, **kwargs})


class FakeCallbackQuery:
    def __init__(self, data: str, *, user_id: int | None = 100500) -> None:
        self.data = data
        self.from_user = FakeUser(user_id) if user_id is not None else None
        self.message = FakeMessage("/inbox")
        self.answers: list[dict[str, Any]] = []

    async def answer(self, text: str | None = None, **kwargs: Any) -> None:
        self.answers.append({"text": text, **kwargs})


class FakeEventScalarRows:
    def __init__(self, items: list[EventItem]) -> None:
        self.items = items

    def all(self) -> list[EventItem]:
        return self.items


class FakeEventListResult:
    def __init__(self, items: list[EventItem]) -> None:
        self.items = items

    def scalars(self) -> FakeEventScalarRows:
        return FakeEventScalarRows(self.items)


class FakeEventAsyncSession(AsyncSession):
    def __init__(self, items: list[EventItem]) -> None:
        self.items = items
        self.executed: list[Any] = []

    async def execute(self, statement: Any) -> FakeEventListResult:
        self.executed.append(statement)
        return FakeEventListResult(self.items)


def _event_item_model(*, card_json: Any) -> EventItem:
    return EventItem(
        id=uuid4(),
        user_id=100500,
        chat_id=100500,
        scope=EventScope.PERSONAL.value,
        event_type=EventType.REMINDER.value,
        title="Событие fallback",
        body="Карточка события временно недоступна.",
        priority=EventPriority.NORMAL.value,
        status=EventStatus.NEW.value,
        source="test",
        payload_json={},
        card_json=card_json,
        due_at=None,
        created_at=NOW,
        updated_at=NOW,
    )


@pytest.mark.asyncio
async def test_inbox_command_shows_personal_household_and_not_work() -> None:
    service = EventItemService.in_memory(now_factory=lambda: NOW)
    await service.create_event(
        EventItemCreate(
            user_id=100500,
            chat_id=100500,
            scope=EventScope.PERSONAL,
            event_type=EventType.REMINDER,
            title="Личное напоминание",
            body="Позвонить домой",
            source="manual",
            card_json={
                "type": "reminder",
                "title": "Личное напоминание",
                "severity": "info",
                "facts": [{"label": "Когда", "value": "Сегодня"}],
                "summary": "Позвонить домой",
                "actions": [{"id": "done", "label": "Готово"}],
            },
        )
    )
    await service.create_event(
        EventItemCreate(
            user_id=100500,
            chat_id=-100123,
            scope=EventScope.HOUSEHOLD,
            event_type=EventType.SHOPPING,
            title="Домашний список",
            body="Купить молоко",
            source="shopping",
            priority=EventPriority.HIGH,
        )
    )
    await service.create_event(
        EventItemCreate(
            user_id=100500,
            chat_id=-100777,
            scope=EventScope.WORK,
            event_type=EventType.HELPDESK_TICKET,
            title="HelpDesk GLPI #0047513",
            body="Выход сотрудника",
            source="helpdesk",
            priority=EventPriority.CRITICAL,
        )
    )
    message = FakeMessage("/inbox")

    await event_inbox.cmd_inbox(
        message,  # type: ignore[arg-type]
        event_item_service=service,
    )

    rendered = "\n".join(answer["text"] for answer in message.answers)
    assert "Домашний список" in rendered
    assert "Личное напоминание" in rendered
    assert "HelpDesk GLPI" not in rendered
    assert message.answers[0]["parse_mode"] == "HTML"


@pytest.mark.asyncio
async def test_inbox_command_falls_back_for_wrong_shaped_repository_card_json() -> None:
    session = FakeEventAsyncSession([_event_item_model(card_json="broken-json-shape")])
    message = FakeMessage("/inbox")

    await event_inbox.cmd_inbox(
        message,  # type: ignore[arg-type]
        db_session=session,
    )

    assert len(message.answers) == 1
    answer = message.answers[0]
    assert answer["parse_mode"] == "HTML"
    assert "<b>Событие fallback</b>" in answer["text"]
    assert "Карточка события временно недоступна." in answer["text"]
    assert "broken-json-shape" not in answer["text"]
    assert "{" not in answer["text"]
    assert "}" not in answer["text"]


@pytest.mark.asyncio
async def test_work_command_shows_work_and_not_personal_household() -> None:
    service = EventItemService.in_memory(now_factory=lambda: NOW)
    await service.create_event(
        EventItemCreate(
            user_id=100500,
            chat_id=100500,
            scope=EventScope.PERSONAL,
            event_type=EventType.NOTE,
            title="Личное",
            body="Не рабочее",
            source="manual",
        )
    )
    await service.create_event(
        EventItemCreate(
            user_id=100500,
            chat_id=-100777,
            scope=EventScope.WORK,
            event_type=EventType.HELPDESK_TICKET,
            title="HelpDesk GLPI #0047513",
            body="Рабочая заявка",
            source="helpdesk",
            priority=EventPriority.HIGH,
        )
    )
    message = FakeMessage("/work")

    await event_inbox.cmd_work(
        message,  # type: ignore[arg-type]
        event_item_service=service,
    )

    rendered = "\n".join(answer["text"] for answer in message.answers)
    assert "HelpDesk GLPI #0047513" in rendered
    assert "Личное" not in rendered


@pytest.mark.asyncio
async def test_inbox_and_work_empty_states() -> None:
    service = EventItemService.in_memory(now_factory=lambda: NOW)
    inbox_message = FakeMessage("/inbox")
    work_message = FakeMessage("/work")

    await event_inbox.cmd_inbox(
        inbox_message,  # type: ignore[arg-type]
        event_item_service=service,
    )
    await event_inbox.cmd_work(
        work_message,  # type: ignore[arg-type]
        event_item_service=service,
    )

    assert inbox_message.answers == [{"text": "В личном inbox пока нет активных событий."}]
    assert work_message.answers == [{"text": "В рабочем inbox пока нет активных событий."}]


@pytest.mark.asyncio
async def test_event_callback_done_snooze_details_are_minimally_handled() -> None:
    service = EventItemService.in_memory(now_factory=lambda: NOW)
    event = await service.create_event(
        EventItemCreate(
            user_id=100500,
            chat_id=100500,
            scope=EventScope.PERSONAL,
            event_type=EventType.REMINDER,
            title="Напоминание",
            body="Проверить чайник",
            source="manual",
            card_json={
                "type": "reminder",
                "title": "Напоминание",
                "severity": "info",
                "facts": [],
                "summary": "Проверить чайник",
                "actions": [
                    {"id": "done", "label": "Готово"},
                    {"id": "snooze", "label": "Позже"},
                    {"id": "details", "label": "Подробнее"},
                ],
            },
        )
    )
    settings = Settings(admin_telegram_ids="100500")

    done = FakeCallbackQuery(build_event_callback_data("done", event.id))
    await event_inbox.handle_event_callback(
        done,  # type: ignore[arg-type]
        settings=settings,
        event_item_service=service,
    )
    assert done.answers == [{"text": "Готово.", "show_alert": False}]
    assert (await service.get_event(event.id)).status == "done"

    snoozed_event = await service.create_event(
        EventItemCreate(
            user_id=100500,
            chat_id=100500,
            scope=EventScope.PERSONAL,
            event_type=EventType.REMINDER,
            title="Позже",
            body="Вернуться к событию",
            source="manual",
        )
    )
    snooze = FakeCallbackQuery(build_event_callback_data("snooze", snoozed_event.id))
    await event_inbox.handle_event_callback(
        snooze,  # type: ignore[arg-type]
        settings=settings,
        event_item_service=service,
    )
    assert snooze.answers == [{"text": "Отложил.", "show_alert": False}]
    assert (await service.get_event(snoozed_event.id)).status == "snoozed"

    details = FakeCallbackQuery(build_event_callback_data("details", snoozed_event.id))
    await event_inbox.handle_event_callback(
        details,  # type: ignore[arg-type]
        settings=settings,
        event_item_service=service,
    )
    assert details.message.answers
    assert "Позже" in details.message.answers[0]["text"]


@pytest.mark.asyncio
async def test_event_callback_is_access_gated() -> None:
    service = EventItemService.in_memory(now_factory=lambda: NOW)
    event = await service.create_event(
        EventItemCreate(
            user_id=100500,
            chat_id=100500,
            scope=EventScope.PERSONAL,
            event_type=EventType.REMINDER,
            title="Напоминание",
            body="Проверить чайник",
            source="manual",
        )
    )
    callback = FakeCallbackQuery(build_event_callback_data("done", event.id), user_id=7)

    await event_inbox.handle_event_callback(
        callback,  # type: ignore[arg-type]
        settings=Settings(admin_telegram_ids="100500"),
        event_item_service=service,
    )

    assert callback.answers == [{"text": "Доступ запрещён.", "show_alert": True}]
    assert (await service.get_event(event.id)).status == "new"
