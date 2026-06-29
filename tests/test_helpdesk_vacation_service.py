from datetime import UTC, datetime, timedelta

import pytest

from app.services.helpdesk_vacation import (
    HelpdeskVacationService,
    InMemoryHelpdeskVacationRepository,
    build_helpdesk_vacation_review_keyboard,
    format_helpdesk_vacation_review_html,
)

NOW = datetime(2026, 6, 29, 9, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_vacation_state_defaults_disabled_and_toggle_is_idempotent() -> None:
    repository = InMemoryHelpdeskVacationRepository()
    service = HelpdeskVacationService(repository, now_factory=lambda: NOW)

    default = await service.get_state()
    first_on = await service.enable(actor_user_id=100500)
    second_on = await service.enable(actor_user_id=100500)
    first_off = await service.disable(actor_user_id=100500)
    second_off = await service.disable(actor_user_id=100500)

    assert default.enabled is False
    assert default.enabled_at is None
    assert first_on.enabled is True
    assert first_on.enabled_at == NOW
    assert first_on.enabled_by_user_id == 100500
    assert second_on.enabled_at == first_on.enabled_at
    assert first_off.enabled is False
    assert first_off.disabled_at == NOW
    assert first_off.disabled_by_user_id == 100500
    assert second_off.disabled_at == first_off.disabled_at


@pytest.mark.asyncio
async def test_vacation_review_cursor_shows_first_all_then_only_new_items() -> None:
    repository = InMemoryHelpdeskVacationRepository()
    current_time = NOW
    service = HelpdeskVacationService(repository, now_factory=lambda: current_time)
    await service.enable(actor_user_id=100500)
    repository.add_review_event(
        glpi_ticket_id="0047513",
        title="Выход нового сотрудника",
        event_type="new_ticket",
        created_at=NOW + timedelta(minutes=1),
        telegram_chat_id=-100123,
        work_item_id="ticket-1",
        work_item_status="waiting_ack",
    )
    repository.add_review_event(
        glpi_ticket_id="0046692",
        title="Наведение порядка",
        event_type="comment",
        created_at=NOW + timedelta(minutes=2),
        telegram_chat_id=-100123,
        work_item_id="ticket-2",
        work_item_status="in_work",
    )

    first = await service.review_items(telegram_chat_id=-100123)
    current_time = NOW + timedelta(minutes=3)
    await service.mark_reviewed()
    second = await service.review_items(telegram_chat_id=-100123)
    repository.add_review_event(
        glpi_ticket_id="0046692",
        title="Наведение порядка",
        event_type="comment",
        created_at=NOW + timedelta(minutes=5),
        telegram_chat_id=-100123,
        work_item_id="ticket-2",
        work_item_status="in_work",
    )
    third = await service.review_items(telegram_chat_id=-100123)

    assert [item.glpi_ticket_id for item in first] == ["0047513", "0046692"]
    assert [item.events_count for item in first] == [1, 1]
    assert second == []
    assert [item.glpi_ticket_id for item in third] == ["0046692"]
    assert third[0].events_count == 1


@pytest.mark.asyncio
async def test_vacation_review_does_not_advance_cursor_before_explicit_mark_reviewed() -> None:
    repository = InMemoryHelpdeskVacationRepository()
    service = HelpdeskVacationService(repository, now_factory=lambda: NOW)
    await service.enable(actor_user_id=100500)
    repository.add_review_event(
        glpi_ticket_id="0047513",
        title="Выход нового сотрудника",
        event_type="new_ticket",
        created_at=NOW + timedelta(minutes=1),
        telegram_chat_id=-100123,
        work_item_id="ticket-1",
        work_item_status="waiting_ack",
    )

    first = await service.review_items(telegram_chat_id=-100123)
    state_before_send = await service.get_state()
    second = await service.review_items(telegram_chat_id=-100123)

    assert first == second
    assert state_before_send.last_reviewed_at is None


def test_vacation_review_format_groups_by_ticket_and_escapes_html() -> None:
    repository = InMemoryHelpdeskVacationRepository()
    repository.add_review_event(
        glpi_ticket_id="0047513",
        title="Выход <нового> сотрудника",
        event_type="new_ticket",
        created_at=NOW + timedelta(minutes=1),
        telegram_chat_id=-100123,
        work_item_id="ticket-1",
        work_item_status="waiting_ack",
    )
    repository.add_review_event(
        glpi_ticket_id="0047513",
        title="Выход <нового> сотрудника",
        event_type="comment",
        created_at=NOW + timedelta(minutes=2),
        telegram_chat_id=-100123,
        work_item_id="ticket-1",
        work_item_status="waiting_ack",
    )
    items = repository.preview_review_items(telegram_chat_id=-100123)

    rendered = format_helpdesk_vacation_review_html(items)
    keyboard = build_helpdesk_vacation_review_keyboard(items)

    assert "Новые заявки за отпуск" in rendered
    assert "1. GLPI #0047513" in rendered
    assert "Событий: 2" in rendered
    assert "Статус: не взята" in rendered
    assert "Выход &lt;нового&gt; сотрудника" in rendered
    assert "<нового>" not in rendered
    assert keyboard is not None
    assert [button.text for row in keyboard.inline_keyboard for button in row] == [
        "0047513: В работу",
        "0047513: Готово",
    ]
