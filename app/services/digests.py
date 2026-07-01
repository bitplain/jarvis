from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from html import escape
from typing import Protocol
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.db.models import EventScope, EventType
from app.services.event_items import EventItemRepositoryProtocol, StoredEventItem
from app.services.telegram_formatting import TELEGRAM_HTML_LIMIT

DEFAULT_DIGEST_TIMEZONE = "Europe/Moscow"
DIGEST_GRACE_WINDOW_MINUTES = 30
DIGEST_ITEM_LIMIT = 15
PERSONAL_MORNING_DIGEST_KEY = "personal_morning"
WORK_START_DIGEST_KEY = "work_start"
_ELLIPSIS = "…"


@dataclass(frozen=True)
class DigestPolicyInput:
    key: str
    title: str
    enabled: bool
    scope_filter_json: dict[str, list[str]]
    send_time: str
    timezone: str = DEFAULT_DIGEST_TIMEZONE
    target_chat_id: int | None = None
    last_sent_date: date | None = None
    last_sent_at: datetime | None = None

    @classmethod
    def default_personal(cls) -> DigestPolicyInput:
        return cls(
            key=PERSONAL_MORNING_DIGEST_KEY,
            title="Личный утренний дайджест",
            enabled=True,
            scope_filter_json={
                "scopes": [EventScope.PERSONAL.value, EventScope.HOUSEHOLD.value]
            },
            send_time="06:50",
        )

    @classmethod
    def default_work(cls) -> DigestPolicyInput:
        return cls(
            key=WORK_START_DIGEST_KEY,
            title="Рабочий дайджест",
            enabled=True,
            scope_filter_json={"scopes": [EventScope.WORK.value]},
            send_time="09:00",
        )


@dataclass
class StoredDigestPolicy:
    id: str
    key: str
    title: str
    enabled: bool
    scope_filter_json: dict[str, list[str]]
    send_time: str
    timezone: str
    target_chat_id: int | None
    last_sent_date: date | None
    last_sent_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class DigestResult:
    policy: StoredDigestPolicy
    now: datetime
    timezone: ZoneInfo
    scopes: list[str]
    items: list[StoredEventItem]


class DigestPolicyRepositoryProtocol(Protocol):
    async def ensure_default_policies(self) -> list[StoredDigestPolicy]:
        raise NotImplementedError

    async def list_policies(self) -> list[StoredDigestPolicy]:
        raise NotImplementedError

    async def get_by_key(self, key: str) -> StoredDigestPolicy | None:
        raise NotImplementedError

    async def update_enabled(self, key: str, enabled: bool) -> StoredDigestPolicy | None:
        raise NotImplementedError

    async def update_schedule(
        self,
        key: str,
        *,
        send_time: str | None,
        timezone: str | None,
    ) -> StoredDigestPolicy | None:
        raise NotImplementedError

    async def set_target_chat_id(
        self,
        key: str,
        target_chat_id: int,
    ) -> StoredDigestPolicy | None:
        raise NotImplementedError

    async def due_for_delivery(self, now: datetime) -> list[StoredDigestPolicy]:
        raise NotImplementedError

    async def mark_sent_if_due(
        self,
        key: str,
        local_date: date,
        *,
        sent_at: datetime,
    ) -> bool:
        raise NotImplementedError


class DigestService:
    def __init__(
        self,
        *,
        policy_repository: DigestPolicyRepositoryProtocol,
        event_repository: EventItemRepositoryProtocol,
        item_limit: int = DIGEST_ITEM_LIMIT,
    ) -> None:
        self.policy_repository = policy_repository
        self.event_repository = event_repository
        self.item_limit = item_limit

    async def build_digest(self, policy_key: str, *, now: datetime) -> DigestResult:
        await self.policy_repository.ensure_default_policies()
        policy = await self.policy_repository.get_by_key(policy_key)
        if policy is None:
            raise ValueError("unknown_digest_policy")
        timezone = _timezone(policy.timezone)
        scopes = _scope_filter(policy.scope_filter_json)
        items = await self.event_repository.list_for_digest(
            scopes=set(scopes),
            now=_to_utc(now),
            limit=self.item_limit,
        )
        return DigestResult(
            policy=policy,
            now=(
                now.astimezone(timezone)
                if now.tzinfo is not None
                else now.replace(tzinfo=timezone)
            ),
            timezone=timezone,
            scopes=scopes,
            items=items,
        )


class InMemoryDigestPolicyRepository:
    def __init__(self, *, now_factory: object | None = None) -> None:
        del now_factory
        self.policies: dict[str, StoredDigestPolicy] = {}

    async def ensure_default_policies(self) -> list[StoredDigestPolicy]:
        for policy_input in _default_policy_inputs():
            if policy_input.key not in self.policies:
                self.policies[policy_input.key] = _stored_from_input(policy_input)
        return await self.list_policies()

    async def list_policies(self) -> list[StoredDigestPolicy]:
        keys = [PERSONAL_MORNING_DIGEST_KEY, WORK_START_DIGEST_KEY]
        return [self.policies[key] for key in keys if key in self.policies]

    async def get_by_key(self, key: str) -> StoredDigestPolicy | None:
        await self.ensure_default_policies()
        return self.policies.get(_normalize_key(key))

    async def update_enabled(self, key: str, enabled: bool) -> StoredDigestPolicy | None:
        policy = await self.get_by_key(key)
        if policy is None:
            return None
        policy.enabled = enabled
        policy.updated_at = utc_now()
        return policy

    async def update_schedule(
        self,
        key: str,
        *,
        send_time: str | None,
        timezone: str | None,
    ) -> StoredDigestPolicy | None:
        policy = await self.get_by_key(key)
        if policy is None:
            return None
        if send_time is not None:
            _validate_send_time(send_time)
            policy.send_time = send_time
        if timezone is not None:
            _timezone(timezone)
            policy.timezone = timezone
        policy.updated_at = utc_now()
        return policy

    async def set_target_chat_id(
        self,
        key: str,
        target_chat_id: int,
    ) -> StoredDigestPolicy | None:
        policy = await self.get_by_key(key)
        if policy is None:
            return None
        policy.target_chat_id = target_chat_id
        policy.updated_at = utc_now()
        return policy

    async def due_for_delivery(self, now: datetime) -> list[StoredDigestPolicy]:
        await self.ensure_default_policies()
        return [
            policy
            for policy in await self.list_policies()
            if _is_policy_due(policy, now, grace_minutes=DIGEST_GRACE_WINDOW_MINUTES)
        ]

    async def mark_sent_if_due(
        self,
        key: str,
        local_date: date,
        *,
        sent_at: datetime,
    ) -> bool:
        policy = await self.get_by_key(key)
        if policy is None or policy.last_sent_date == local_date:
            return False
        policy.last_sent_date = local_date
        policy.last_sent_at = _to_utc(sent_at)
        policy.updated_at = utc_now()
        return True


def render_digest(result: DigestResult) -> str:
    lines = [_digest_title(result), ""]
    if not result.items:
        lines.append("Новых событий нет.")
        return _truncate_html("\n".join(lines))

    grouped = _group_digest_items(result)
    for group_index, (header, items) in enumerate(grouped):
        if group_index:
            lines.append("")
        lines.append(f"<b>{escape(header)}</b>")
        for index, item in enumerate(items, start=1):
            lines.append(f"{index}. {_format_digest_item(item, result.timezone)}")
    lines.append("")
    lines.append(_open_command_hint(result.policy.key))
    return _truncate_html("\n".join(lines))


def _default_policy_inputs() -> list[DigestPolicyInput]:
    return [DigestPolicyInput.default_personal(), DigestPolicyInput.default_work()]


def _stored_from_input(policy: DigestPolicyInput) -> StoredDigestPolicy:
    _validate_send_time(policy.send_time)
    _timezone(policy.timezone)
    scopes = _scope_filter(policy.scope_filter_json)
    now = utc_now()
    return StoredDigestPolicy(
        id=uuid4().hex,
        key=_normalize_key(policy.key),
        title=policy.title,
        enabled=policy.enabled,
        scope_filter_json={"scopes": scopes},
        send_time=policy.send_time,
        timezone=policy.timezone,
        target_chat_id=policy.target_chat_id,
        last_sent_date=policy.last_sent_date,
        last_sent_at=policy.last_sent_at,
        created_at=now,
        updated_at=now,
    )


def _scope_filter(value: Mapping[str, object]) -> list[str]:
    raw_scopes = value.get("scopes")
    if not isinstance(raw_scopes, list):
        raise ValueError("invalid_digest_scope_filter")
    scopes: list[str] = []
    allowed = {scope.value for scope in EventScope}
    for raw_scope in raw_scopes:
        scope = str(raw_scope).strip().lower()
        if scope not in allowed:
            raise ValueError("invalid_digest_scope")
        if scope not in scopes:
            scopes.append(scope)
    if not scopes:
        raise ValueError("invalid_digest_scope_filter")
    return scopes


def _is_policy_due(policy: StoredDigestPolicy, now: datetime, *, grace_minutes: int) -> bool:
    if not policy.enabled or policy.target_chat_id is None:
        return False
    timezone = _timezone(policy.timezone)
    local_now = now.astimezone(timezone) if now.tzinfo is not None else now.replace(tzinfo=timezone)
    scheduled = datetime.combine(
        local_now.date(),
        _parse_send_time(policy.send_time),
        tzinfo=timezone,
    )
    deadline = scheduled + timedelta(minutes=grace_minutes)
    if not (scheduled <= local_now <= deadline):
        return False
    return policy.last_sent_date != local_now.date()


def _validate_send_time(value: str) -> None:
    _parse_send_time(value)


def _parse_send_time(value: str) -> time:
    try:
        hour_text, minute_text = value.split(":", maxsplit=1)
        hour = int(hour_text)
        minute = int(minute_text)
    except ValueError as exc:
        raise ValueError("invalid_digest_send_time") from exc
    if len(value) != 5 or not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("invalid_digest_send_time")
    return time(hour=hour, minute=minute)


def _timezone(value: str) -> ZoneInfo:
    try:
        return ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("invalid_digest_timezone") from exc


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def utc_now() -> datetime:
    return datetime.now(UTC)


def _normalize_key(value: str) -> str:
    return value.strip().lower()


def _digest_title(result: DigestResult) -> str:
    if result.policy.key == PERSONAL_MORNING_DIGEST_KEY:
        return "<b>🌅 Личный утренний дайджест</b>"
    if result.policy.key == WORK_START_DIGEST_KEY:
        return "<b>💼 Рабочий дайджест</b>"
    return f"<b>{escape(result.policy.title)}</b>"


def _group_digest_items(result: DigestResult) -> list[tuple[str, list[StoredEventItem]]]:
    group_order = _group_order(result.policy.key)
    grouped: dict[str, list[StoredEventItem]] = {header: [] for header in group_order}
    for item in result.items:
        grouped.setdefault(_group_title(item, result.policy.key), []).append(item)
    return [(header, grouped[header]) for header in grouped if grouped[header]]


def _group_order(policy_key: str) -> list[str]:
    if policy_key == WORK_START_DIGEST_KEY:
        return ["🎫 HelpDesk / работа", "⏰ Рабочие напоминания", "🧠 Рабочие заметки", "📌 Другое"]
    return ["🛒 Покупки", "⏰ Напоминания", "🧠 Заметки", "📌 Другое"]


def _group_title(item: StoredEventItem, policy_key: str) -> str:
    if item.event_type == EventType.SHOPPING.value:
        return "🛒 Покупки"
    if item.event_type == EventType.REMINDER.value:
        return "⏰ Рабочие напоминания" if policy_key == WORK_START_DIGEST_KEY else "⏰ Напоминания"
    if item.event_type == EventType.HELPDESK_TICKET.value:
        return "🎫 HelpDesk / работа"
    if item.event_type == EventType.NOTE.value:
        return "🧠 Рабочие заметки" if policy_key == WORK_START_DIGEST_KEY else "🧠 Заметки"
    return "📌 Другое"


def _format_digest_item(item: StoredEventItem, timezone: ZoneInfo) -> str:
    title = _safe_text(item.title)
    body = _safe_body(item.body)
    prefix = ""
    if item.due_at is not None:
        prefix = f"{escape(item.due_at.astimezone(timezone).strftime('%H:%M'))} — "
    suffix = f" — {body}" if body else ""
    return f"{prefix}{title}{suffix}"


def _safe_text(value: str) -> str:
    return escape(" ".join(value.strip().split()), quote=True)


def _safe_body(value: str) -> str:
    cleaned = " ".join(value.strip().split())
    if not cleaned or cleaned.startswith("{") or cleaned.startswith("["):
        return ""
    return escape(cleaned, quote=True)


def _open_command_hint(policy_key: str) -> str:
    if policy_key == WORK_START_DIGEST_KEY:
        return "<i>Открыть: /work</i>"
    return "<i>Открыть: /inbox</i>"


def _truncate_html(text: str) -> str:
    if len(text) <= TELEGRAM_HTML_LIMIT:
        return text
    return text[: TELEGRAM_HTML_LIMIT - len(_ELLIPSIS)] + _ELLIPSIS
