from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from app.db.models import EventStatus
from app.services.digests import DigestService, InMemoryDigestPolicyRepository, render_digest
from app.services.event_cards import render_card_to_telegram_text
from app.services.event_items import EventItemService
from app.services.telegram_formatting import TELEGRAM_HTML_LIMIT
from app.services.whoop_cards import (
    build_whoop_sleep_card,
    upsert_latest_whoop_sleep_event,
)

NOW = datetime(2026, 7, 2, 6, 50, tzinfo=UTC)
INTEGRATION_ID = uuid4()
USER_ID = 100500
UNFINISHED_ENTITY_RE = re.compile(
    r"&(?:#[0-9]*|#x[0-9a-fA-F]*|[a-zA-Z][a-zA-Z0-9]*)?$"
)


def _sleep(
    *,
    sleep_id: str = "sleep-1",
    cycle_id: int = 101,
    score_state: str = "SCORED",
    nap: bool = False,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    raw_json: dict[str, Any] | None = None,
) -> SimpleNamespace:
    start = start_at or datetime(2026, 7, 1, 21, 30, tzinfo=UTC)
    end = end_at or datetime(2026, 7, 2, 5, 45, tzinfo=UTC)
    return SimpleNamespace(
        integration_id=INTEGRATION_ID,
        user_id=USER_ID,
        whoop_sleep_id=sleep_id,
        cycle_id=cycle_id,
        start_at=start,
        end_at=end,
        timezone_offset="+03:00",
        nap=nap,
        score_state=score_state,
        raw_json=raw_json
        or {
            "id": sleep_id,
            "cycle_id": cycle_id,
            "score_state": score_state,
            "score": {
                "sleep_performance_percentage": 88,
            },
        },
        created_at=start,
        updated_at=end,
    )


def _recovery(
    *,
    cycle_id: int = 101,
    recovery_score: Any = 77,
    hrv: Any = 33.5,
    rhr: Any = 61,
) -> SimpleNamespace:
    return SimpleNamespace(
        integration_id=INTEGRATION_ID,
        user_id=USER_ID,
        cycle_id=cycle_id,
        score_state="SCORED",
        recovery_score=recovery_score,
        hrv_rmssd_milli=hrv,
        resting_heart_rate=rhr,
        raw_json={"cycle_id": cycle_id, "score": {"recovery_score": recovery_score}},
        created_at=NOW,
        updated_at=NOW,
    )


class FakeWhoopCardRepository:
    def __init__(
        self,
        *,
        sleeps: list[SimpleNamespace] | None = None,
        recoveries: list[SimpleNamespace] | None = None,
    ) -> None:
        self.sleeps = sleeps or []
        self.recoveries = recoveries or []

    async def list_recent_sleep_records(
        self,
        integration_id: str,
        *,
        since: datetime,
        limit: int,
    ) -> list[SimpleNamespace]:
        del limit
        return [
            sleep
            for sleep in self.sleeps
            if str(sleep.integration_id) == integration_id and sleep.start_at >= since
        ]

    async def get_recovery_by_cycle_id(
        self,
        integration_id: str,
        *,
        cycle_id: int,
    ) -> SimpleNamespace | None:
        for recovery in self.recoveries:
            if str(recovery.integration_id) == integration_id and recovery.cycle_id == cycle_id:
                return recovery
        return None


def _assert_safe_telegram_html(html: str) -> None:
    assert len(html) <= TELEGRAM_HTML_LIMIT
    assert html.count("<b>") == html.count("</b>")
    assert not re.search(r"<[^>]*$", html)
    assert UNFINISHED_ENTITY_RE.search(html) is None


def test_build_whoop_sleep_card_scored_sleep_and_recovery_builds_facts() -> None:
    card = build_whoop_sleep_card(
        sleep=_sleep(),
        recovery=_recovery(),
        integration_id=str(INTEGRATION_ID),
    )

    assert card["type"] == "whoop_sleep"
    assert card["title"] == "WHOOP: сон"
    assert card["severity"] == "success"
    assert card["summary"] == "Данные WHOOP готовы. Это техническая сводка сна и восстановления."
    assert card["actions"] == [
        {"id": "details", "label": "Подробнее"},
        {"id": "done", "label": "Ок"},
    ]
    facts = {fact["label"]: fact["value"] for fact in card["facts"]}
    assert facts["Сон"] == "8 ч 15 мин"
    assert facts["Recovery"] == "77%"
    assert facts["HRV"] == "33.5 ms"
    assert facts["RHR"] == "61 bpm"
    assert facts["Score"] == "88%"
    assert "raw_json" not in str(card)


def test_build_whoop_sleep_card_pending_unscorable_and_missing_values_are_safe() -> None:
    pending_card = build_whoop_sleep_card(
        sleep=_sleep(score_state="PENDING_SCORE", raw_json={"id": "sleep-1"}),
        recovery=None,
        integration_id=str(INTEGRATION_ID),
    )
    unscorable_card = build_whoop_sleep_card(
        sleep=_sleep(score_state="UNSCORABLE", raw_json={"id": "sleep-2"}),
        recovery=None,
        integration_id=str(INTEGRATION_ID),
    )

    assert pending_card["severity"] == "info"
    assert pending_card["summary"] == (
        "WHOOP ещё считает сон. Данные обновятся после следующей синхронизации."
    )
    assert unscorable_card["summary"] == "WHOOP не смог рассчитать score для этого сна."
    assert {fact["value"] for fact in pending_card["facts"]} >= {"нет данных"}


def test_build_whoop_sleep_card_tolerates_string_numeric_fields_and_escapes_html() -> None:
    card = build_whoop_sleep_card(
        sleep=_sleep(
            raw_json={
                "id": "sleep-1",
                "score_state": "SCORED",
                "score": {"sleep_performance_percentage": "66.0"},
            },
        ),
        recovery=_recovery(recovery_score="33.0", hrv="42.25", rhr="59.0"),
        integration_id=str(INTEGRATION_ID),
    )
    html = render_card_to_telegram_text(
        {
            **card,
            "facts": card["facts"] + [{"label": "<сырой>", "value": "<json> & token"}],
            "summary": card["summary"] + " <без диагноза>",
        }
    )

    facts = {fact["label"]: fact["value"] for fact in card["facts"]}
    assert card["severity"] == "warning"
    assert facts["Recovery"] == "33%"
    assert facts["HRV"] == "42.25 ms"
    assert facts["RHR"] == "59 bpm"
    assert facts["Score"] == "66%"
    assert "<сырой>" not in html
    assert "<json>" not in html
    assert "&lt;сырой&gt;" in html
    assert "&lt;json&gt; &amp; token" in html
    _assert_safe_telegram_html(html)


@pytest.mark.asyncio
async def test_upsert_latest_whoop_sleep_event_creates_one_personal_event_and_digest_item() -> None:
    events = EventItemService.in_memory(now_factory=lambda: NOW)
    whoop = FakeWhoopCardRepository(sleeps=[_sleep()], recoveries=[_recovery()])

    event = await upsert_latest_whoop_sleep_event(
        whoop_repository=whoop,
        event_repository=events.repository,
        integration_id=str(INTEGRATION_ID),
        now=NOW,
    )
    repeated = await upsert_latest_whoop_sleep_event(
        whoop_repository=whoop,
        event_repository=events.repository,
        integration_id=str(INTEGRATION_ID),
        now=NOW + timedelta(minutes=5),
    )
    policies = InMemoryDigestPolicyRepository()
    digest_service = DigestService(
        policy_repository=policies,
        event_repository=events.repository,
    )

    inbox = await events.list_for_inbox(user_id=USER_ID, chat_id=USER_ID)
    work = await events.list_for_work(user_id=USER_ID, chat_id=USER_ID)
    personal_digest = await digest_service.build_digest("personal_morning", now=NOW)
    work_digest = await digest_service.build_digest("work_start", now=NOW)
    html = render_digest(personal_digest)

    assert event is not None
    assert repeated is not None
    assert repeated.id == event.id
    assert len(events.repository.items) == 1
    assert event.scope == "personal"
    assert event.event_type == "whoop_sleep"
    assert event.source == "whoop"
    assert event.payload_json == {
        "identity_key": f"whoop_sleep:{INTEGRATION_ID}:sleep-1",
        "integration_id": str(INTEGRATION_ID),
        "sleep_id": "sleep-1",
        "cycle_id": 101,
        "score_state": "SCORED",
    }
    assert event.id in {item.id for item in inbox}
    assert event.id not in {item.id for item in work}
    assert event.id in {item.id for item in personal_digest.items}
    assert event.id not in {item.id for item in work_digest.items}
    assert "WHOOP: сон" in html
    assert "техническая сводка" in html
    assert "raw_json" not in html


@pytest.mark.asyncio
async def test_upsert_latest_whoop_sleep_event_updates_done_pending_to_scored() -> None:
    events = EventItemService.in_memory(now_factory=lambda: NOW)
    pending_sleep = _sleep(score_state="PENDING_SCORE", raw_json={"id": "sleep-1"})
    whoop = FakeWhoopCardRepository(sleeps=[pending_sleep], recoveries=[])

    pending_event = await upsert_latest_whoop_sleep_event(
        whoop_repository=whoop,
        event_repository=events.repository,
        integration_id=str(INTEGRATION_ID),
        now=NOW,
    )
    assert pending_event is not None
    await events.mark_done(pending_event.id)
    pending_sleep.score_state = "SCORED"
    pending_sleep.raw_json = {
        "id": "sleep-1",
        "score_state": "SCORED",
        "score": {"sleep_performance_percentage": 91},
    }
    whoop.recoveries = [_recovery(recovery_score=70)]

    scored_event = await upsert_latest_whoop_sleep_event(
        whoop_repository=whoop,
        event_repository=events.repository,
        integration_id=str(INTEGRATION_ID),
        now=NOW + timedelta(hours=1),
    )

    assert scored_event is not None
    assert scored_event.id == pending_event.id
    assert scored_event.status == EventStatus.DONE.value
    assert scored_event.card_json is not None
    assert scored_event.card_json["summary"] == (
        "Данные WHOOP готовы. Это техническая сводка сна и восстановления."
    )
    assert scored_event.card_json["severity"] == "success"
    assert len(events.repository.items) == 1


@pytest.mark.asyncio
async def test_upsert_latest_whoop_sleep_event_noops_without_non_nap_sleep_records() -> None:
    events = EventItemService.in_memory(now_factory=lambda: NOW)
    whoop = FakeWhoopCardRepository(
        sleeps=[
            _sleep(nap=True),
            _sleep(
                sleep_id="old-sleep",
                start_at=NOW - timedelta(days=4),
                end_at=NOW - timedelta(days=4, hours=-8),
            ),
        ],
        recoveries=[_recovery()],
    )

    event = await upsert_latest_whoop_sleep_event(
        whoop_repository=whoop,
        event_repository=events.repository,
        integration_id=str(INTEGRATION_ID),
        now=NOW,
    )

    assert event is None
    assert events.repository.items == {}
