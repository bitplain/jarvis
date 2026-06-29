from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from html import escape
from typing import Protocol
from uuid import uuid4
from zoneinfo import ZoneInfo

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

HELPDESK_VACATION_SCOPE = "default"
HELPDESK_VACATION_NOTIFY_STATUS = "suppressed_vacation"
HELPDESK_VACATION_ERROR_CODE = "vacation"
MOSCOW_TZ = ZoneInfo("Europe/Moscow")


@dataclass
class StoredHelpdeskVacationState:
    id: str
    scope: str
    enabled: bool
    enabled_at: datetime | None
    disabled_at: datetime | None
    last_reviewed_at: datetime | None
    enabled_by_user_id: int | None
    disabled_by_user_id: int | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class HelpdeskVacationSummary:
    enabled: bool
    enabled_at: datetime | None
    disabled_at: datetime | None
    last_reviewed_at: datetime | None
    events_since_start: int
    events_since_last_review: int


@dataclass(frozen=True)
class HelpdeskVacationReviewItem:
    glpi_ticket_id: str
    title: str
    event_type: str | None
    events_count: int
    work_item_id: str | None
    work_item_status: str | None


class HelpdeskVacationRepositoryProtocol(Protocol):
    async def get_or_create_state(
        self,
        *,
        scope: str = HELPDESK_VACATION_SCOPE,
    ) -> StoredHelpdeskVacationState: ...

    async def enable(
        self,
        *,
        scope: str,
        actor_user_id: int | None,
        now: datetime,
    ) -> StoredHelpdeskVacationState: ...

    async def disable(
        self,
        *,
        scope: str,
        actor_user_id: int | None,
        now: datetime,
    ) -> StoredHelpdeskVacationState: ...

    async def mark_reviewed(
        self,
        *,
        scope: str,
        now: datetime,
    ) -> StoredHelpdeskVacationState: ...

    async def count_review_events(
        self,
        *,
        since: datetime | None,
        after: datetime | None,
        until: datetime | None,
        telegram_chat_id: int,
    ) -> int: ...

    async def review_items(
        self,
        *,
        since: datetime | None,
        after: datetime | None,
        until: datetime | None,
        telegram_chat_id: int,
    ) -> list[HelpdeskVacationReviewItem]: ...


class HelpdeskVacationService:
    def __init__(
        self,
        repository: HelpdeskVacationRepositoryProtocol,
        *,
        scope: str = HELPDESK_VACATION_SCOPE,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.scope = scope
        self.now_factory = now_factory or (lambda: datetime.now(UTC))

    async def get_state(self) -> StoredHelpdeskVacationState:
        return await self.repository.get_or_create_state(scope=self.scope)

    async def is_enabled(self) -> bool:
        return (await self.get_state()).enabled

    async def enable(self, *, actor_user_id: int | None) -> StoredHelpdeskVacationState:
        return await self.repository.enable(
            scope=self.scope,
            actor_user_id=actor_user_id,
            now=_to_utc(self.now_factory()),
        )

    async def disable(self, *, actor_user_id: int | None) -> StoredHelpdeskVacationState:
        return await self.repository.disable(
            scope=self.scope,
            actor_user_id=actor_user_id,
            now=_to_utc(self.now_factory()),
        )

    async def mark_reviewed(self) -> StoredHelpdeskVacationState:
        return await self.repository.mark_reviewed(
            scope=self.scope,
            now=_to_utc(self.now_factory()),
        )

    async def summary(self, *, telegram_chat_id: int) -> HelpdeskVacationSummary:
        state = await self.get_state()
        since_start = await self.repository.count_review_events(
            since=state.enabled_at,
            after=None,
            until=state.disabled_at if not state.enabled else None,
            telegram_chat_id=telegram_chat_id,
        )
        since_last_review = await self.repository.count_review_events(
            since=state.enabled_at,
            after=state.last_reviewed_at,
            until=state.disabled_at if not state.enabled else None,
            telegram_chat_id=telegram_chat_id,
        )
        return HelpdeskVacationSummary(
            enabled=state.enabled,
            enabled_at=state.enabled_at,
            disabled_at=state.disabled_at,
            last_reviewed_at=state.last_reviewed_at,
            events_since_start=since_start,
            events_since_last_review=since_last_review,
        )

    async def review_items(self, *, telegram_chat_id: int) -> list[HelpdeskVacationReviewItem]:
        state = await self.get_state()
        return await self.repository.review_items(
            since=state.enabled_at,
            after=state.last_reviewed_at,
            until=state.disabled_at if not state.enabled else None,
            telegram_chat_id=telegram_chat_id,
        )


class InMemoryHelpdeskVacationRepository:
    def __init__(self) -> None:
        now = datetime.now(UTC)
        self.state = StoredHelpdeskVacationState(
            id=uuid4().hex,
            scope=HELPDESK_VACATION_SCOPE,
            enabled=False,
            enabled_at=None,
            disabled_at=None,
            last_reviewed_at=None,
            enabled_by_user_id=None,
            disabled_by_user_id=None,
            created_at=now,
            updated_at=now,
        )
        self.events: list[dict[str, object]] = []

    async def get_or_create_state(
        self,
        *,
        scope: str = HELPDESK_VACATION_SCOPE,
    ) -> StoredHelpdeskVacationState:
        del scope
        return replace(self.state)

    async def enable(
        self,
        *,
        scope: str,
        actor_user_id: int | None,
        now: datetime,
    ) -> StoredHelpdeskVacationState:
        del scope
        if self.state.enabled:
            return replace(self.state)
        self.state.enabled = True
        self.state.enabled_at = now
        self.state.disabled_at = None
        self.state.last_reviewed_at = None
        self.state.enabled_by_user_id = actor_user_id
        self.state.updated_at = now
        return replace(self.state)

    async def disable(
        self,
        *,
        scope: str,
        actor_user_id: int | None,
        now: datetime,
    ) -> StoredHelpdeskVacationState:
        del scope
        if not self.state.enabled:
            return replace(self.state)
        self.state.enabled = False
        self.state.disabled_at = now
        self.state.disabled_by_user_id = actor_user_id
        self.state.updated_at = now
        return replace(self.state)

    async def mark_reviewed(
        self,
        *,
        scope: str,
        now: datetime,
    ) -> StoredHelpdeskVacationState:
        del scope
        self.state.last_reviewed_at = now
        self.state.updated_at = now
        return replace(self.state)

    async def count_review_events(
        self,
        *,
        since: datetime | None,
        after: datetime | None,
        until: datetime | None,
        telegram_chat_id: int,
    ) -> int:
        return len(
            self._filtered_events(
                since=since,
                after=after,
                until=until,
                telegram_chat_id=telegram_chat_id,
            )
        )

    async def review_items(
        self,
        *,
        since: datetime | None,
        after: datetime | None,
        until: datetime | None,
        telegram_chat_id: int,
    ) -> list[HelpdeskVacationReviewItem]:
        return _group_review_events(
            self._filtered_events(
                since=since,
                after=after,
                until=until,
                telegram_chat_id=telegram_chat_id,
            )
        )

    def add_review_event(
        self,
        *,
        glpi_ticket_id: str,
        title: str,
        event_type: str,
        created_at: datetime,
        telegram_chat_id: int,
        work_item_id: str | None,
        work_item_status: str | None,
    ) -> None:
        self.events.append(
            {
                "glpi_ticket_id": glpi_ticket_id,
                "title": title,
                "event_type": event_type,
                "created_at": created_at,
                "telegram_chat_id": telegram_chat_id,
                "notify_status": HELPDESK_VACATION_NOTIFY_STATUS,
                "work_item_id": work_item_id,
                "work_item_status": work_item_status,
            }
        )

    def preview_review_items(self, *, telegram_chat_id: int) -> list[HelpdeskVacationReviewItem]:
        return _group_review_events(
            self._filtered_events(
                since=None,
                after=None,
                until=None,
                telegram_chat_id=telegram_chat_id,
            )
        )

    def _filtered_events(
        self,
        *,
        since: datetime | None,
        after: datetime | None,
        until: datetime | None,
        telegram_chat_id: int,
    ) -> list[dict[str, object]]:
        result: list[dict[str, object]] = []
        for event in self.events:
            created_at = _to_utc(event["created_at"])  # type: ignore[arg-type]
            if event.get("notify_status") != HELPDESK_VACATION_NOTIFY_STATUS:
                continue
            event_chat_id = event.get("telegram_chat_id")
            if not isinstance(event_chat_id, int) or event_chat_id != telegram_chat_id:
                continue
            if since is not None and created_at < _to_utc(since):
                continue
            if after is not None and created_at <= _to_utc(after):
                continue
            if until is not None and created_at > _to_utc(until):
                continue
            result.append(event)
        return sorted(result, key=lambda item: _to_utc(item["created_at"]))  # type: ignore[arg-type]


def format_helpdesk_vacation_summary_text(summary: HelpdeskVacationSummary) -> str:
    status = "on" if summary.enabled else "off"
    return (
        "HelpDesk\n\n"
        f"Vacation mode: {status}\n"
        f"Vacation since: {_format_dt(summary.enabled_at)}\n"
        f"Vacation last reviewed: {_format_dt(summary.last_reviewed_at)}\n"
        f"Новых событий с начала отпуска: {summary.events_since_start}\n"
        f"Новых событий с прошлого просмотра: {summary.events_since_last_review}\n\n"
        "Действия:"
    )


def build_helpdesk_vacation_keyboard(*, enabled: bool) -> InlineKeyboardMarkup:
    toggle = InlineKeyboardButton(
        text="Выключить отпуск" if enabled else "Включить отпуск",
        callback_data="hd_vacation:off" if enabled else "hd_vacation:on",
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [toggle],
            [
                InlineKeyboardButton(
                    text="Показать новые за отпуск",
                    callback_data="hd_vacation:review",
                )
            ],
        ]
    )


def format_helpdesk_vacation_review_html(
    items: list[HelpdeskVacationReviewItem],
) -> str:
    if not items:
        return "Новых заявок с прошлого просмотра нет."
    lines = ["<b>Новые заявки за отпуск</b>", ""]
    for index, item in enumerate(items, start=1):
        event_label = "Новая заявка" if item.event_type == "new_ticket" else "Новый комментарий"
        lines.append(f"{index}. GLPI #{escape(item.glpi_ticket_id)}")
        lines.append(f"{event_label}: {escape(item.title)}")
        lines.append(f"Событий: {item.events_count}")
        lines.append(f"Статус: {_status_label(item.work_item_status)}")
        if index != len(items):
            lines.append("")
    return "\n".join(lines)


def build_helpdesk_vacation_review_keyboard(
    items: list[HelpdeskVacationReviewItem],
) -> InlineKeyboardMarkup | None:
    rows: list[list[InlineKeyboardButton]] = []
    for item in items:
        if not item.work_item_id or item.work_item_status == "done":
            continue
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{item.glpi_ticket_id}: В работу",
                    callback_data=f"hd_ticket:take:{item.work_item_id}",
                ),
                InlineKeyboardButton(
                    text=f"{item.glpi_ticket_id}: Готово",
                    callback_data=f"hd_ticket:done:{item.work_item_id}",
                ),
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def _group_review_events(events: list[dict[str, object]]) -> list[HelpdeskVacationReviewItem]:
    grouped: dict[str, list[dict[str, object]]] = {}
    for event in events:
        ticket_id = str(event.get("glpi_ticket_id") or "").strip()
        if not ticket_id:
            continue
        grouped.setdefault(ticket_id, []).append(event)
    items: list[HelpdeskVacationReviewItem] = []
    for ticket_id, ticket_events in grouped.items():
        sorted_events = sorted(
            ticket_events,
            key=lambda event: _to_utc(event["created_at"]),  # type: ignore[arg-type]
        )
        latest = sorted_events[-1]
        items.append(
            HelpdeskVacationReviewItem(
                glpi_ticket_id=ticket_id,
                title=str(latest.get("title") or "Без темы"),
                event_type=str(latest.get("event_type") or ""),
                events_count=len(sorted_events),
                work_item_id=(
                    str(latest["work_item_id"]) if latest.get("work_item_id") is not None else None
                ),
                work_item_status=(
                    str(latest["work_item_status"])
                    if latest.get("work_item_status") is not None
                    else None
                ),
            )
        )
    return items


def _status_label(status: str | None) -> str:
    labels = {
        "waiting_ack": "не взята",
        "in_work": "в работе",
        "done": "готово",
        "dismissed": "скрыта",
    }
    return labels.get(status or "", "неизвестно")


def _format_dt(value: datetime | None) -> str:
    if value is None:
        return "unknown"
    return _to_utc(value).astimezone(MOSCOW_TZ).strftime("%d.%m.%Y %H:%M МСК")


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
