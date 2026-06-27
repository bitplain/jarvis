from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from app.services.daily_brief_service import (
    DailyBriefService,
    DailyBriefSettingsInput,
    InMemoryDailyBriefSettingsRepository,
)
from app.services.household_memory_service import HouseholdMemoryService
from app.services.reminder_service import ReminderService
from app.services.shopping_service import ShoppingService
from app.services.telegram_formatting import format_daily_brief_html

MSK = ZoneInfo("Europe/Moscow")


@pytest.mark.asyncio
async def test_daily_brief_private_scope_includes_reminders_shopping_and_memory() -> None:
    shopping = ShoppingService.in_memory()
    reminders = ReminderService.in_memory(
        now_factory=lambda: datetime(2026, 6, 27, 8, 0, tzinfo=UTC)
    )
    memory = HouseholdMemoryService(InMemoryMemoryRepository())
    service = DailyBriefService(
        shopping=shopping,
        reminders=reminders,
        household_memory=memory,
    )

    await reminders.create_reminder(
        "private",
        100500,
        100500,
        "купить молоко",
        datetime(2026, 6, 27, 10, 0, tzinfo=MSK),
    )
    await reminders.create_reminder(
        "private",
        100500,
        100500,
        "проверить backup",
        datetime(2026, 6, 26, 21, 0, tzinfo=MSK),
    )
    await shopping.add_items("private", 100500, 100500, ["молоко 2 шт", "хлеб"])
    await memory.add_memory("private", 100500, 100500, "семейный чат Фемилис")

    brief = await service.build_brief(
        scope_type="private",
        chat_id=100500,
        user_id=100500,
        now=datetime(2026, 6, 27, 8, 0, tzinfo=MSK),
        timezone=MSK,
    )

    html = format_daily_brief_html(brief)
    assert "<b>📋 Сводка дня</b>" in html
    assert "10:00 — купить молоко" in html
    assert "вчера 21:00 — проверить backup" in html
    assert "молоко — 2 шт" in html
    assert "семейный чат Фемилис" in html


@pytest.mark.asyncio
async def test_daily_brief_settings_send_once_per_local_day() -> None:
    repository = InMemoryDailyBriefSettingsRepository()
    settings = await repository.upsert(
        DailyBriefSettingsInput(
            scope_type="private",
            chat_id=100500,
            user_id=100500,
            enabled=True,
            send_time="09:00",
            timezone="Europe/Moscow",
        )
    )

    due = await repository.due_for_delivery(datetime(2026, 6, 27, 9, 0, tzinfo=MSK))
    marked = await repository.mark_sent_if_due(settings.id, "2026-06-27")
    repeated = await repository.mark_sent_if_due(settings.id, "2026-06-27")
    next_day = await repository.due_for_delivery(datetime(2026, 6, 28, 9, 0, tzinfo=MSK))

    assert [item.id for item in due] == [settings.id]
    assert marked is True
    assert repeated is False
    assert [item.id for item in next_day] == [settings.id]


class InMemoryMemoryRepository:
    def __init__(self) -> None:
        self.entries: list[object] = []

    async def active_count(self, *, scope_type: str, scope_chat_id: int) -> int:
        return len(
            [
                entry
                for entry in self.entries
                if entry.scope_type == scope_type and entry.scope_chat_id == scope_chat_id
            ]
        )

    async def create(
        self,
        *,
        scope_type: str,
        scope_chat_id: int,
        created_by_user_id: int,
        text: str,
    ) -> object:
        entry = type(
            "MemoryEntry",
            (),
            {
                "id": str(len(self.entries) + 1),
                "scope_type": scope_type,
                "scope_chat_id": scope_chat_id,
                "created_by_user_id": created_by_user_id,
                "text": text,
                "status": "active",
            },
        )()
        self.entries.append(entry)
        return entry

    async def list_active(
        self,
        *,
        scope_type: str,
        scope_chat_id: int,
        limit: int = 100,
    ) -> list[object]:
        return [
            entry
            for entry in self.entries
            if entry.scope_type == scope_type and entry.scope_chat_id == scope_chat_id
        ][:limit]

    async def soft_delete(self, *, memory_id: str, actor_user_id: int) -> object | None:
        del memory_id, actor_user_id
        return None
