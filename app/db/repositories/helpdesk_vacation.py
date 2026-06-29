from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.db.models import HelpdeskEmailEvent, HelpdeskTicketWorkItem, HelpdeskVacationState
from app.services.helpdesk_vacation import (
    HELPDESK_VACATION_NOTIFY_STATUS,
    HELPDESK_VACATION_SCOPE,
    HelpdeskVacationReviewItem,
    StoredHelpdeskVacationState,
)


class HelpdeskVacationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_or_create_state(
        self,
        *,
        scope: str = HELPDESK_VACATION_SCOPE,
    ) -> StoredHelpdeskVacationState:
        state = await self._get_state(scope=scope)
        if state is not None:
            return _to_stored(state)
        state = HelpdeskVacationState(scope=scope)
        self.session.add(state)
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            state = await self._get_state(scope=scope)
            if state is None:
                raise
            return _to_stored(state)
        await self.session.refresh(state)
        return _to_stored(state)

    async def enable(
        self,
        *,
        scope: str,
        actor_user_id: int | None,
        now: datetime,
    ) -> StoredHelpdeskVacationState:
        await self.get_or_create_state(scope=scope)
        state = await self._get_state_required(scope=scope)
        if state.enabled:
            return _to_stored(state)
        state.enabled = True
        state.enabled_at = now
        state.disabled_at = None
        state.last_reviewed_at = None
        state.enabled_by_user_id = actor_user_id
        state.updated_at = now
        await self.session.commit()
        await self.session.refresh(state)
        return _to_stored(state)

    async def disable(
        self,
        *,
        scope: str,
        actor_user_id: int | None,
        now: datetime,
    ) -> StoredHelpdeskVacationState:
        await self.get_or_create_state(scope=scope)
        state = await self._get_state_required(scope=scope)
        if not state.enabled:
            return _to_stored(state)
        state.enabled = False
        state.disabled_at = now
        state.disabled_by_user_id = actor_user_id
        state.updated_at = now
        await self.session.commit()
        await self.session.refresh(state)
        return _to_stored(state)

    async def mark_reviewed(
        self,
        *,
        scope: str,
        now: datetime,
    ) -> StoredHelpdeskVacationState:
        await self.get_or_create_state(scope=scope)
        state = await self._get_state_required(scope=scope)
        state.last_reviewed_at = now
        state.updated_at = now
        await self.session.commit()
        await self.session.refresh(state)
        return _to_stored(state)

    async def count_review_events(
        self,
        *,
        since: datetime | None,
        after: datetime | None,
        until: datetime | None,
        telegram_chat_id: int,
    ) -> int:
        conditions = _event_conditions(
            since=since,
            after=after,
            until=until,
            telegram_chat_id=telegram_chat_id,
        )
        result = await self.session.execute(
            select(func.count(HelpdeskEmailEvent.id)).where(*conditions)
        )
        return int(result.scalar_one())

    async def review_items(
        self,
        *,
        since: datetime | None,
        after: datetime | None,
        until: datetime | None,
        telegram_chat_id: int,
    ) -> list[HelpdeskVacationReviewItem]:
        conditions = _event_conditions(
            since=since,
            after=after,
            until=until,
            telegram_chat_id=telegram_chat_id,
        )
        result = await self.session.execute(
            select(HelpdeskEmailEvent).where(*conditions).order_by(HelpdeskEmailEvent.created_at)
        )
        events = list(result.scalars().all())
        ticket_ids = sorted(
            {
                event.glpi_ticket_id
                for event in events
                if event.glpi_ticket_id is not None and event.glpi_ticket_id.strip()
            }
        )
        work_items_by_ticket: dict[str, HelpdeskTicketWorkItem] = {}
        if ticket_ids:
            work_result = await self.session.execute(
                select(HelpdeskTicketWorkItem).where(
                    HelpdeskTicketWorkItem.telegram_chat_id == telegram_chat_id,
                    HelpdeskTicketWorkItem.glpi_ticket_id.in_(ticket_ids),
                )
            )
            work_items_by_ticket = {
                item.glpi_ticket_id: item for item in work_result.scalars().all()
            }
        grouped: dict[str, list[HelpdeskEmailEvent]] = {}
        for event in events:
            ticket_id = (event.glpi_ticket_id or "").strip()
            if not ticket_id:
                continue
            grouped.setdefault(ticket_id, []).append(event)
        items: list[HelpdeskVacationReviewItem] = []
        for ticket_id, ticket_events in grouped.items():
            latest = ticket_events[-1]
            work_item = work_items_by_ticket.get(ticket_id)
            items.append(
                HelpdeskVacationReviewItem(
                    glpi_ticket_id=ticket_id,
                    title=_title_for_event(latest, work_item),
                    event_type=latest.event_type,
                    events_count=len(ticket_events),
                    work_item_id=str(work_item.id) if work_item is not None else None,
                    work_item_status=work_item.status if work_item is not None else None,
                )
            )
        return items

    async def _get_state(self, *, scope: str) -> HelpdeskVacationState | None:
        result = await self.session.execute(
            select(HelpdeskVacationState).where(HelpdeskVacationState.scope == scope)
        )
        return result.scalar_one_or_none()

    async def _get_state_required(self, *, scope: str) -> HelpdeskVacationState:
        state = await self._get_state(scope=scope)
        if state is None:
            raise RuntimeError("helpdesk_vacation_state_missing")
        return state


def _event_conditions(
    *,
    since: datetime | None,
    after: datetime | None,
    until: datetime | None,
    telegram_chat_id: int,
) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = [
        HelpdeskEmailEvent.notify_status == HELPDESK_VACATION_NOTIFY_STATUS,
        HelpdeskEmailEvent.telegram_chat_id == telegram_chat_id,
    ]
    if since is not None:
        conditions.append(HelpdeskEmailEvent.created_at >= since)
    if after is not None:
        conditions.append(HelpdeskEmailEvent.created_at > after)
    if until is not None:
        conditions.append(HelpdeskEmailEvent.created_at <= until)
    return conditions


def _title_for_event(
    event: HelpdeskEmailEvent,
    work_item: HelpdeskTicketWorkItem | None,
) -> str:
    if work_item is not None and work_item.title.strip():
        return work_item.title
    return event.subject.strip() or "Без темы"


def _to_stored(state: HelpdeskVacationState) -> StoredHelpdeskVacationState:
    return StoredHelpdeskVacationState(
        id=str(state.id),
        scope=state.scope,
        enabled=state.enabled,
        enabled_at=state.enabled_at,
        disabled_at=state.disabled_at,
        last_reviewed_at=state.last_reviewed_at,
        enabled_by_user_id=state.enabled_by_user_id,
        disabled_by_user_id=state.disabled_by_user_id,
        created_at=state.created_at,
        updated_at=state.updated_at,
    )
