from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.services.reminder_service import ReminderService

MSK = ZoneInfo("Europe/Moscow")


@pytest.mark.asyncio
async def test_reminder_create_stores_utc_and_lists_scheduled() -> None:
    service = ReminderService.in_memory()
    remind_at = datetime(2026, 6, 27, 10, 0, tzinfo=MSK)

    created = await service.create_reminder("private", 100500, 100500, "купить молоко", remind_at)
    reminders = await service.list_reminders("private", 100500, user_id=100500)

    assert created.remind_at == datetime(2026, 6, 27, 7, 0, tzinfo=UTC)
    assert [reminder.text for reminder in reminders] == ["купить молоко"]


@pytest.mark.asyncio
async def test_reminder_cancel_snooze_due_and_sent_idempotency() -> None:
    now = datetime(2026, 6, 26, 12, 0, tzinfo=UTC)
    service = ReminderService.in_memory(now_factory=lambda: now)
    reminder = await service.create_reminder(
        "group",
        -100123,
        100500,
        "проверить духовку",
        now - timedelta(minutes=1),
    )

    due = await service.due_reminders(now)
    await service.mark_sent(reminder.id)
    repeated_due = await service.due_reminders(now)
    await service.mark_sent(reminder.id)
    snoozed = await service.snooze_reminder(reminder.id, timedelta(minutes=10), 100500)
    cancelled = await service.cancel_reminder(reminder.id, 100500)

    assert [item.id for item in due] == [reminder.id]
    assert repeated_due == []
    assert snoozed.remind_at == now + timedelta(minutes=10)
    assert cancelled == []
