from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from app.db.models import EventPriority, EventScope, EventType
from app.services.event_items import EventItemCreate, EventItemRepositoryProtocol, EventItemService

WHOOP_SLEEP_EVENT_SOURCE = "whoop"
WHOOP_SLEEP_CARD_TYPE = "whoop_sleep"
WHOOP_SLEEP_CARD_TITLE = "WHOOP: сон"
WHOOP_SLEEP_LOOKBACK_HOURS = 72
WHOOP_SLEEP_RECORD_LIMIT = 20
_NO_DATA = "нет данных"


class WhoopCardRepositoryProtocol(Protocol):
    async def list_recent_sleep_records(
        self,
        integration_id: str,
        *,
        since: datetime,
        limit: int,
    ) -> list[Any]:
        raise NotImplementedError

    async def get_recovery_by_cycle_id(
        self,
        integration_id: str,
        *,
        cycle_id: int,
    ) -> Any | None:
        raise NotImplementedError


def build_whoop_sleep_card(
    *,
    sleep: Any,
    recovery: Any | None,
    integration_id: str,
    ) -> dict[str, Any]:
    del integration_id
    state = _score_state(sleep)
    recovery_score = _decimal_or_none(_attr(recovery, "recovery_score"))
    score_value = _sleep_score_value(sleep)
    return {
        "type": WHOOP_SLEEP_CARD_TYPE,
        "title": WHOOP_SLEEP_CARD_TITLE,
        "severity": _severity(state, recovery_score),
        "facts": [
            {"label": "Сон", "value": _sleep_duration_text(sleep)},
            {"label": "Recovery", "value": _percent_or_no_data(recovery_score)},
            {
                "label": "HRV",
                "value": _unit_or_no_data(_attr(recovery, "hrv_rmssd_milli"), "ms"),
            },
            {
                "label": "RHR",
                "value": _unit_or_no_data(_attr(recovery, "resting_heart_rate"), "bpm"),
            },
            {"label": "Score", "value": _percent_or_no_data(score_value)},
        ],
        "summary": _summary(state),
        "actions": [
            {"id": "details", "label": "Подробнее"},
            {"id": "done", "label": "Ок"},
        ],
    }


async def upsert_latest_whoop_sleep_event(
    *,
    whoop_repository: WhoopCardRepositoryProtocol,
    event_repository: EventItemRepositoryProtocol,
    integration_id: str,
    now: datetime,
    lookback_hours: int = WHOOP_SLEEP_LOOKBACK_HOURS,
) -> Any | None:
    resolved_now = _to_utc(now)
    since = resolved_now - timedelta(hours=lookback_hours)
    sleeps = await whoop_repository.list_recent_sleep_records(
        str(integration_id),
        since=since,
        limit=WHOOP_SLEEP_RECORD_LIMIT,
    )
    sleep = _select_sleep_record(sleeps, since=since)
    if sleep is None:
        return None
    recovery = await whoop_repository.get_recovery_by_cycle_id(
        str(integration_id),
        cycle_id=int(sleep.cycle_id),
    )
    card = build_whoop_sleep_card(
        sleep=sleep,
        recovery=recovery,
        integration_id=str(integration_id),
    )
    identity_key = _identity_key(integration_id=str(integration_id), sleep=sleep)
    payload = {
        "identity_key": identity_key,
        "integration_id": str(integration_id),
        "sleep_id": str(sleep.whoop_sleep_id),
        "cycle_id": int(sleep.cycle_id),
        "score_state": _score_state(sleep),
    }
    service = EventItemService(event_repository, now_factory=lambda: resolved_now)
    return await service.upsert_event_by_payload_identity(
        EventItemCreate(
            user_id=_int_or_none(_attr(sleep, "user_id")),
            chat_id=_int_or_none(_attr(sleep, "user_id")),
            scope=EventScope.PERSONAL,
            event_type=EventType.WHOOP_SLEEP,
            title=WHOOP_SLEEP_CARD_TITLE,
            body=str(card["summary"]),
            source=WHOOP_SLEEP_EVENT_SOURCE,
            priority=EventPriority.NORMAL,
            payload_json=payload,
            card_json=card,
        ),
        identity_key=identity_key,
    )


def _select_sleep_record(sleeps: list[Any], *, since: datetime) -> Any | None:
    candidates = [
        sleep
        for sleep in sleeps
        if not _truthy(_attr(sleep, "nap", False))
        and _to_utc(sleep.start_at) >= since
    ]
    if not candidates:
        return None
    for state in ("SCORED", "PENDING_SCORE", "UNSCORABLE"):
        matching = [sleep for sleep in candidates if _score_state(sleep) == state]
        if matching:
            return max(matching, key=lambda sleep: _to_utc(sleep.start_at))
    return None


def _identity_key(*, integration_id: str, sleep: Any) -> str:
    return f"whoop_sleep:{integration_id}:{sleep.whoop_sleep_id}"


def _score_state(sleep: Any) -> str:
    return str(_attr(sleep, "score_state", "") or "").strip().upper()


def _summary(state: str) -> str:
    if state == "PENDING_SCORE":
        return "WHOOP ещё считает сон. Данные обновятся после следующей синхронизации."
    if state == "UNSCORABLE":
        return "WHOOP не смог рассчитать score для этого сна."
    return "Данные WHOOP готовы. Это техническая сводка сна и восстановления."


def _severity(state: str, recovery_score: Decimal | None) -> str:
    if state == "PENDING_SCORE" or recovery_score is None:
        return "info"
    if recovery_score >= Decimal(67):
        return "success"
    if recovery_score >= Decimal(34):
        return "info"
    return "warning"


def _sleep_duration_text(sleep: Any) -> str:
    start = _datetime_or_none(_attr(sleep, "start_at"))
    end = _datetime_or_none(_attr(sleep, "end_at"))
    if start is None or end is None or end <= start:
        return _NO_DATA
    total_minutes = int((end - start).total_seconds() // 60)
    hours, minutes = divmod(total_minutes, 60)
    if hours and minutes:
        return f"{hours} ч {minutes} мин"
    if hours:
        return f"{hours} ч"
    return f"{minutes} мин"


def _sleep_score_value(sleep: Any) -> Decimal | None:
    raw = _attr(sleep, "raw_json")
    if not isinstance(raw, Mapping):
        return None
    score = raw.get("score")
    if not isinstance(score, Mapping):
        return None
    for key in (
        "sleep_performance_percentage",
        "sleep_performance_score",
        "sleep_score",
        "score",
    ):
        parsed = _decimal_or_none(score.get(key))
        if parsed is not None:
            return parsed
    return None


def _percent_or_no_data(value: Any) -> str:
    numeric = _decimal_or_none(value)
    if numeric is None:
        return _NO_DATA
    return f"{_format_decimal(numeric)}%"


def _unit_or_no_data(value: Any, unit: str) -> str:
    numeric = _decimal_or_none(value)
    if numeric is None:
        return _NO_DATA
    return f"{_format_decimal(numeric)} {unit}"


def _format_decimal(value: Decimal) -> str:
    if value == value.to_integral_value():
        return str(int(value))
    return format(value.normalize(), "f").rstrip("0").rstrip(".")


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        numeric = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    if not numeric.is_finite():
        return None
    return numeric


def _int_or_none(value: Any) -> int | None:
    numeric = _decimal_or_none(value)
    if numeric is None or numeric != numeric.to_integral_value():
        return None
    return int(numeric)


def _datetime_or_none(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return _to_utc(value)


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _attr(value: Any, name: str, default: Any = None) -> Any:
    return getattr(value, name, default)
