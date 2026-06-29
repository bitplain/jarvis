from datetime import UTC, datetime, timedelta

import pytest

from app.services.helpdesk_ticket_workflow import (
    HelpdeskTicketWorkflowService,
    InMemoryHelpdeskTicketWorkItemRepository,
    format_helpdesk_ticket_reminder_html,
)

NOW = datetime(2026, 6, 29, 9, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_new_ticket_creates_waiting_ack_work_item_and_dedupes_same_glpi_ticket() -> None:
    repository = InMemoryHelpdeskTicketWorkItemRepository()
    service = HelpdeskTicketWorkflowService(repository, now_factory=lambda: NOW)

    first = await service.create_or_update_waiting_ack(
        glpi_ticket_id="0047513",
        latest_event_id="11111111-1111-4111-8111-111111111111",
        title="Выход <нового> сотрудника",
        telegram_chat_id=-100123,
    )
    second = await service.create_or_update_waiting_ack(
        glpi_ticket_id="0047513",
        latest_event_id="22222222-2222-4222-8222-222222222222",
        title="Выход нового сотрудника обновлён",
        telegram_chat_id=-100123,
    )

    assert first.id == second.id
    assert second.status == "waiting_ack"
    assert second.reminder_interval_minutes == 10
    assert second.next_reminder_at == NOW + timedelta(minutes=10)
    assert second.title == "Выход нового сотрудника обновлён"
    assert len(repository.items) == 1


@pytest.mark.asyncio
async def test_done_ticket_is_not_reopened_by_duplicate_email_for_same_glpi_ticket() -> None:
    repository = InMemoryHelpdeskTicketWorkItemRepository()
    service = HelpdeskTicketWorkflowService(repository, now_factory=lambda: NOW)
    item = await service.create_or_update_waiting_ack(
        glpi_ticket_id="0047513",
        latest_event_id=None,
        title="Выход нового сотрудника",
        telegram_chat_id=-100123,
    )
    await service.mark_done(item.id, actor_user_id=100500, telegram_chat_id=-100123)

    updated = await service.create_or_update_waiting_ack(
        glpi_ticket_id="0047513",
        latest_event_id=None,
        title="Повторное письмо",
        telegram_chat_id=-100123,
    )

    assert updated.id == item.id
    assert updated.status == "done"
    assert updated.next_reminder_at is None


@pytest.mark.asyncio
async def test_take_list_snooze_done_and_due_reminder_intervals() -> None:
    repository = InMemoryHelpdeskTicketWorkItemRepository()
    service = HelpdeskTicketWorkflowService(repository, now_factory=lambda: NOW)
    item = await service.create_or_update_waiting_ack(
        glpi_ticket_id="0047513",
        latest_event_id=None,
        title="Выход нового сотрудника",
        telegram_chat_id=-100123,
    )

    waiting_due = await service.due_reminders(NOW + timedelta(minutes=10))
    await service.mark_reminded(item.id, now=NOW + timedelta(minutes=10))
    next_waiting_reminder = repository.items[item.id].next_reminder_at
    taken = await service.take(item.id, actor_user_id=100500, telegram_chat_id=-100123)
    in_work = await service.list_in_work(telegram_chat_id=-100123)
    snoozed = await service.snooze(item.id, minutes=60, telegram_chat_id=-100123)
    done = await service.mark_done(item.id, actor_user_id=100500, telegram_chat_id=-100123)
    after_done_due = await service.due_reminders(NOW + timedelta(hours=2))

    assert [due.id for due in waiting_due] == [item.id]
    assert next_waiting_reminder == NOW + timedelta(minutes=20)
    assert taken.status == "in_work"
    assert taken.assigned_by_user_id == 100500
    assert taken.reminder_interval_minutes == 30
    assert taken.next_reminder_at == NOW + timedelta(minutes=30)
    assert [view.id for view in in_work] == [item.id]
    assert snoozed.next_reminder_at == NOW + timedelta(hours=1)
    assert done.status == "done"
    assert done.next_reminder_at is None
    assert after_done_due == []


@pytest.mark.asyncio
async def test_helpdesk_ticket_reminder_html_escapes_title_and_uses_status_text() -> None:
    repository = InMemoryHelpdeskTicketWorkItemRepository()
    service = HelpdeskTicketWorkflowService(repository, now_factory=lambda: NOW)
    item = await service.create_or_update_waiting_ack(
        glpi_ticket_id="0047513",
        latest_event_id=None,
        title="Выход <нового> сотрудника",
        telegram_chat_id=-100123,
    )

    html = format_helpdesk_ticket_reminder_html(item)

    assert "Новая заявка GLPI #0047513 ещё не взята в работу." in html
    assert "Выход &lt;нового&gt; сотрудника" in html
    assert "<нового>" not in html
