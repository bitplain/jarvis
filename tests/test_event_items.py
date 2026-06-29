from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.db.models import EventItem, EventPriority, EventScope, EventStatus, EventType
from app.services.event_items import (
    DEFAULT_DIGEST_TIMEZONE,
    EventItemCreate,
    EventItemService,
)

NOW = datetime(2026, 6, 29, 6, 50, tzinfo=UTC)


def test_event_item_model_exposes_foundation_columns_and_enums() -> None:
    columns = set(EventItem.__table__.columns.keys())

    assert EventItem.__tablename__ == "event_items"
    assert {
        "id",
        "user_id",
        "chat_id",
        "scope",
        "event_type",
        "title",
        "body",
        "priority",
        "status",
        "source",
        "payload_json",
        "card_json",
        "due_at",
        "created_at",
        "updated_at",
    } <= columns
    assert [scope.value for scope in EventScope] == ["personal", "household", "work", "system"]
    assert [status.value for status in EventStatus] == [
        "new",
        "seen",
        "done",
        "snoozed",
        "archived",
        "failed",
    ]
    assert [priority.value for priority in EventPriority] == [
        "low",
        "normal",
        "high",
        "critical",
    ]
    assert [event_type.value for event_type in EventType] == [
        "reminder",
        "note",
        "shopping",
        "helpdesk_ticket",
        "whoop_sleep",
        "system_alert",
        "digest_item",
    ]
    assert DEFAULT_DIGEST_TIMEZONE == "Europe/Moscow"


@pytest.mark.asyncio
async def test_create_event_item_defaults_and_preserves_card() -> None:
    service = EventItemService.in_memory(now_factory=lambda: NOW)

    created = await service.create_event(
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
                "facts": [{"label": "Когда", "value": "Сегодня"}],
                "summary": "Проверить чайник",
                "actions": [{"id": "done", "label": "Готово"}],
            },
        )
    )

    assert created.user_id == 100500
    assert created.chat_id == 100500
    assert created.scope == "personal"
    assert created.event_type == "reminder"
    assert created.priority == "normal"
    assert created.status == "new"
    assert created.card_json["facts"][0]["label"] == "Когда"
    assert created.created_at == NOW
    assert created.updated_at == NOW


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_card_json", ["broken-json-shape", ["bad"]])
async def test_create_event_item_normalizes_wrong_shaped_card_json_to_none(
    bad_card_json: Any,
) -> None:
    service = EventItemService.in_memory(now_factory=lambda: NOW)

    created = await service.create_event(
        EventItemCreate(
            user_id=100500,
            chat_id=100500,
            scope=EventScope.PERSONAL,
            event_type=EventType.REMINDER,
            title="Напоминание",
            body="Проверить чайник",
            source="manual",
            card_json=bad_card_json,  # type: ignore[arg-type]
        )
    )

    assert created.card_json is None


@pytest.mark.asyncio
async def test_scope_filtering_excludes_work_from_inbox_and_personal_from_work() -> None:
    service = EventItemService.in_memory(now_factory=lambda: NOW)
    due = NOW + timedelta(hours=2)
    personal = await service.create_event(
        EventItemCreate(
            user_id=100500,
            chat_id=100500,
            scope=EventScope.PERSONAL,
            event_type=EventType.NOTE,
            title="Личное",
            body="Личный контур",
            source="manual",
            priority=EventPriority.NORMAL,
            due_at=due,
        )
    )
    household = await service.create_event(
        EventItemCreate(
            user_id=100500,
            chat_id=-100123,
            scope=EventScope.HOUSEHOLD,
            event_type=EventType.SHOPPING,
            title="Дом",
            body="Домашний контур",
            source="shopping",
            priority=EventPriority.HIGH,
            due_at=None,
        )
    )
    work = await service.create_event(
        EventItemCreate(
            user_id=100500,
            chat_id=-100777,
            scope=EventScope.WORK,
            event_type=EventType.HELPDESK_TICKET,
            title="HelpDesk GLPI #0047513",
            body="Рабочая заявка",
            source="helpdesk",
            priority=EventPriority.CRITICAL,
            due_at=NOW + timedelta(minutes=30),
        )
    )
    system = await service.create_event(
        EventItemCreate(
            user_id=100500,
            chat_id=100500,
            scope=EventScope.SYSTEM,
            event_type=EventType.SYSTEM_ALERT,
            title="Системное",
            body="Не показывать по умолчанию",
            source="system",
            priority=EventPriority.CRITICAL,
        )
    )
    done = await service.create_event(
        EventItemCreate(
            user_id=100500,
            chat_id=100500,
            scope=EventScope.PERSONAL,
            event_type=EventType.REMINDER,
            title="Сделано",
            body="Не активно",
            source="manual",
            priority=EventPriority.CRITICAL,
            status=EventStatus.DONE,
        )
    )

    inbox = await service.list_for_inbox(user_id=100500, chat_id=100500, limit=10)
    work_items = await service.list_for_work(user_id=100500, chat_id=100500, limit=10)

    assert [item.id for item in inbox] == [household.id, personal.id]
    assert work.id not in {item.id for item in inbox}
    assert system.id not in {item.id for item in inbox}
    assert done.id not in {item.id for item in inbox}
    assert [item.id for item in work_items] == [work.id]
    assert personal.id not in {item.id for item in work_items}
    assert household.id not in {item.id for item in work_items}


@pytest.mark.asyncio
async def test_event_sorting_priority_due_nulls_last_and_created_desc() -> None:
    ticks = iter(
        [
            NOW,
            NOW + timedelta(seconds=1),
            NOW + timedelta(seconds=2),
            NOW + timedelta(seconds=3),
        ]
    )
    service = EventItemService.in_memory(now_factory=lambda: next(ticks))

    low_due = await service.create_event(
        EventItemCreate(
            user_id=100500,
            chat_id=100500,
            scope=EventScope.PERSONAL,
            event_type=EventType.NOTE,
            title="Низкий",
            body="Первый",
            source="manual",
            priority=EventPriority.LOW,
            due_at=NOW,
        )
    )
    normal_null_older = await service.create_event(
        EventItemCreate(
            user_id=100500,
            chat_id=100500,
            scope=EventScope.PERSONAL,
            event_type=EventType.NOTE,
            title="Без срока старый",
            body="Второй",
            source="manual",
            priority=EventPriority.NORMAL,
            due_at=None,
        )
    )
    normal_null_newer = await service.create_event(
        EventItemCreate(
            user_id=100500,
            chat_id=100500,
            scope=EventScope.PERSONAL,
            event_type=EventType.NOTE,
            title="Без срока новый",
            body="Третий",
            source="manual",
            priority=EventPriority.NORMAL,
            due_at=None,
        )
    )
    high_due_later = await service.create_event(
        EventItemCreate(
            user_id=100500,
            chat_id=100500,
            scope=EventScope.PERSONAL,
            event_type=EventType.NOTE,
            title="Высокий",
            body="Четвертый",
            source="manual",
            priority=EventPriority.HIGH,
            due_at=NOW + timedelta(days=1),
        )
    )

    inbox = await service.list_for_inbox(user_id=100500, chat_id=100500, limit=10)

    assert [item.id for item in inbox] == [
        high_due_later.id,
        normal_null_newer.id,
        normal_null_older.id,
        low_due.id,
    ]
