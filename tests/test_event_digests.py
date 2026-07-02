import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.db.models import DigestPolicy, EventPriority, EventScope, EventStatus, EventType
from app.services.digests import (
    DEFAULT_DIGEST_TIMEZONE,
    DigestPolicyInput,
    DigestService,
    InMemoryDigestPolicyRepository,
    render_digest,
)
from app.services.event_items import (
    EventItemCreate,
    EventItemService,
    create_household_event,
    create_personal_event,
    create_system_event,
    create_work_event,
)
from app.services.telegram_formatting import TELEGRAM_HTML_LIMIT

MSK = ZoneInfo("Europe/Moscow")
NOW = datetime(2026, 7, 1, 6, 50, tzinfo=MSK)
UNFINISHED_ENTITY_TAILS = ("&", "&q", "&qu", "&#", "&#x")


def _assert_safe_digest_html(html: str) -> None:
    assert len(html) <= TELEGRAM_HTML_LIMIT
    assert html.count("<b>") == html.count("</b>")
    assert not re.search(r"<[^>]*$", html)
    assert not re.search(r"&(?:#[0-9]*|#x[0-9a-fA-F]*|[a-zA-Z][a-zA-Z0-9]*)?$", html)
    assert not re.search(r"&(?:#[0-9]*|#x[0-9a-fA-F]*|[a-zA-Z][a-zA-Z0-9]*)?…$", html)
    assert not html.endswith(UNFINISHED_ENTITY_TAILS)


def test_digest_policy_model_exposes_required_columns() -> None:
    columns = set(DigestPolicy.__table__.columns.keys())

    assert DigestPolicy.__tablename__ == "digest_policies"
    assert {
        "id",
        "key",
        "title",
        "enabled",
        "scope_filter_json",
        "send_time",
        "timezone",
        "target_chat_id",
        "last_sent_date",
        "last_sent_at",
        "created_at",
        "updated_at",
    } <= columns


@pytest.mark.asyncio
async def test_default_digest_policies_are_created_with_hard_scope_filters() -> None:
    repository = InMemoryDigestPolicyRepository()

    policies = await repository.ensure_default_policies()
    personal = await repository.get_by_key("personal_morning")
    work = await repository.get_by_key("work_start")

    assert [policy.key for policy in policies] == ["personal_morning", "work_start"]
    assert personal is not None
    assert personal.title == "Личный утренний дайджест"
    assert personal.enabled is True
    assert personal.send_time == "06:50"
    assert personal.timezone == DEFAULT_DIGEST_TIMEZONE == "Europe/Moscow"
    assert personal.scope_filter_json == {"scopes": ["personal", "household"]}
    assert personal.target_chat_id is None
    assert work is not None
    assert work.title == "Рабочий дайджест"
    assert work.enabled is True
    assert work.send_time == "09:00"
    assert work.timezone == "Europe/Moscow"
    assert work.scope_filter_json == {"scopes": ["work"]}
    assert "system" not in personal.scope_filter_json["scopes"]
    assert "system" not in work.scope_filter_json["scopes"]


@pytest.mark.asyncio
async def test_digest_policy_validates_send_time_and_timezone() -> None:
    repository = InMemoryDigestPolicyRepository()
    await repository.ensure_default_policies()

    with pytest.raises(ValueError, match="invalid_digest_send_time"):
        await repository.update_schedule("personal_morning", send_time="25:99", timezone=None)

    with pytest.raises(ValueError, match="invalid_digest_timezone"):
        await repository.update_schedule(
            "personal_morning",
            send_time=None,
            timezone="Europe/NoSuchCity",
        )


@pytest.mark.asyncio
async def test_due_policies_use_thirty_minute_grace_window_and_send_once_per_day() -> None:
    repository = InMemoryDigestPolicyRepository()
    await repository.ensure_default_policies()
    await repository.set_target_chat_id("personal_morning", 100500)

    before = await repository.due_for_delivery(datetime(2026, 7, 1, 6, 49, tzinfo=MSK))
    due = await repository.due_for_delivery(datetime(2026, 7, 1, 7, 20, tzinfo=MSK))
    after = await repository.due_for_delivery(datetime(2026, 7, 1, 7, 21, tzinfo=MSK))
    marked = await repository.mark_sent_if_due(
        "personal_morning",
        datetime(2026, 7, 1, 7, 20, tzinfo=MSK).date(),
        sent_at=datetime(2026, 7, 1, 4, 20, tzinfo=UTC),
    )
    repeated = await repository.mark_sent_if_due(
        "personal_morning",
        datetime(2026, 7, 1, 7, 20, tzinfo=MSK).date(),
        sent_at=datetime(2026, 7, 1, 4, 21, tzinfo=UTC),
    )
    due_after_mark = await repository.due_for_delivery(datetime(2026, 7, 1, 7, 20, tzinfo=MSK))

    assert before == []
    assert [policy.key for policy in due] == ["personal_morning"]
    assert after == []
    assert marked is True
    assert repeated is False
    assert due_after_mark == []


@pytest.mark.asyncio
async def test_digest_builder_keeps_personal_and_work_scopes_separate() -> None:
    policies = InMemoryDigestPolicyRepository()
    await policies.ensure_default_policies()
    events = EventItemService.in_memory(now_factory=lambda: NOW)
    service = DigestService(policy_repository=policies, event_repository=events.repository)

    personal = await events.create_event(
        EventItemCreate(
            user_id=100500,
            chat_id=100500,
            scope=EventScope.PERSONAL,
            event_type=EventType.REMINDER,
            title="Позвонить врачу",
            body="Записаться на приём",
            source="manual",
            priority=EventPriority.HIGH,
            due_at=NOW + timedelta(hours=5),
        )
    )
    household = await events.create_event(
        EventItemCreate(
            user_id=100500,
            chat_id=-100123,
            scope=EventScope.HOUSEHOLD,
            event_type=EventType.SHOPPING,
            title="молоко",
            body="2 шт",
            source="shopping",
        )
    )
    work = await events.create_event(
        EventItemCreate(
            user_id=100500,
            chat_id=-100777,
            scope=EventScope.WORK,
            event_type=EventType.HELPDESK_TICKET,
            title="GLPI #0047513",
            body="В работе",
            source="helpdesk",
            priority=EventPriority.CRITICAL,
        )
    )
    system = await events.create_event(
        EventItemCreate(
            user_id=None,
            chat_id=None,
            scope=EventScope.SYSTEM,
            event_type=EventType.SYSTEM_ALERT,
            title="Redis warning",
            body="system",
            source="system",
        )
    )

    personal_digest = await service.build_digest("personal_morning", now=NOW)
    work_digest = await service.build_digest("work_start", now=NOW)

    assert [item.id for item in personal_digest.items] == [personal.id, household.id]
    assert work.id not in {item.id for item in personal_digest.items}
    assert system.id not in {item.id for item in personal_digest.items}
    assert [item.id for item in work_digest.items] == [work.id]
    assert personal.id not in {item.id for item in work_digest.items}
    assert household.id not in {item.id for item in work_digest.items}
    assert system.id not in {item.id for item in work_digest.items}


@pytest.mark.asyncio
async def test_digest_builder_excludes_done_archived_failed_and_not_due_snoozed() -> None:
    policies = InMemoryDigestPolicyRepository()
    await policies.ensure_default_policies()
    events = EventItemService.in_memory(now_factory=lambda: NOW)
    service = DigestService(policy_repository=policies, event_repository=events.repository)
    visible = await events.create_event(
        EventItemCreate(
            user_id=100500,
            chat_id=100500,
            scope=EventScope.PERSONAL,
            event_type=EventType.NOTE,
            title="Новая заметка",
            body="visible",
            source="manual",
        )
    )
    due_snoozed = await events.create_event(
        EventItemCreate(
            user_id=100500,
            chat_id=100500,
            scope=EventScope.PERSONAL,
            event_type=EventType.REMINDER,
            title="Отложенное уже пора",
            body="visible",
            source="manual",
            status=EventStatus.SNOOZED,
            due_at=NOW - timedelta(minutes=1),
        )
    )
    for status in [EventStatus.DONE, EventStatus.ARCHIVED, EventStatus.FAILED]:
        await events.create_event(
            EventItemCreate(
                user_id=100500,
                chat_id=100500,
                scope=EventScope.PERSONAL,
                event_type=EventType.NOTE,
                title=f"hidden {status.value}",
                body="hidden",
                source="manual",
                status=status,
            )
        )
    await events.create_event(
        EventItemCreate(
            user_id=100500,
            chat_id=100500,
            scope=EventScope.PERSONAL,
            event_type=EventType.REMINDER,
            title="Отложенное позже",
            body="hidden",
            source="manual",
            status=EventStatus.SNOOZED,
            due_at=NOW + timedelta(hours=1),
        )
    )

    digest = await service.build_digest("personal_morning", now=NOW)

    assert [item.id for item in digest.items] == [due_snoozed.id, visible.id]


@pytest.mark.asyncio
async def test_digest_rendering_escapes_html_hides_json_and_respects_limit() -> None:
    policies = InMemoryDigestPolicyRepository()
    await policies.ensure_default_policies()
    events = EventItemService.in_memory(now_factory=lambda: NOW)
    service = DigestService(policy_repository=policies, event_repository=events.repository)
    await events.create_event(
        EventItemCreate(
            user_id=100500,
            chat_id=100500,
            scope=EventScope.PERSONAL,
            event_type=EventType.NOTE,
            title="<секретная заметка>",
            body='{"raw": "<json>"}' + (" очень длинно" * 500),
            source="manual",
            payload_json={"token": "must-not-render"},
            card_json={"type": "note", "title": "raw json must not render"},
        )
    )

    html = render_digest(await service.build_digest("personal_morning", now=NOW))

    assert "<секретная заметка>" not in html
    assert "&lt;секретная заметка&gt;" in html
    assert "must-not-render" not in html
    assert '{"raw"' not in html
    assert len(html) <= TELEGRAM_HTML_LIMIT


@pytest.mark.parametrize(
    ("case_name", "payload", "escaped_marker", "raw_marker"),
    [
        ("double_quote", '"quote" ', "&quot;quote&quot;", '"quote"'),
        ("single_quote", "'quote' ", "&#x27;quote&#x27;", "'quote'"),
        ("script", "<script>alert(1)</script> ", "&lt;script&gt;", "<script>"),
        ("ampersand", "&value& ", "&amp;value&amp;", "&value&"),
    ],
)
@pytest.mark.asyncio
async def test_digest_long_title_truncates_without_cutting_html_entities(
    case_name: str,
    payload: str,
    escaped_marker: str,
    raw_marker: str,
) -> None:
    del case_name
    policies = InMemoryDigestPolicyRepository()
    await policies.ensure_default_policies()
    events = EventItemService.in_memory(now_factory=lambda: NOW)
    service = DigestService(policy_repository=policies, event_repository=events.repository)
    await events.create_event(
        EventItemCreate(
            user_id=100500,
            chat_id=100500,
            scope=EventScope.PERSONAL,
            event_type=EventType.NOTE,
            title=payload * 700,
            body="Короткое тело",
            source="manual",
            payload_json={"raw": "must-not-render"},
            card_json={"type": "note", "title": "raw json must not render"},
        )
    )

    html = render_digest(await service.build_digest("personal_morning", now=NOW))

    _assert_safe_digest_html(html)
    assert escaped_marker in html
    assert raw_marker not in html
    assert "must-not-render" not in html
    assert "raw json must not render" not in html


@pytest.mark.parametrize(
    ("case_name", "payload", "escaped_marker", "raw_marker"),
    [
        ("double_quote", '"quote" ', "&quot;quote&quot;", '"quote"'),
        ("single_quote", "'quote' ", "&#x27;quote&#x27;", "'quote'"),
        ("script", "<script>alert(1)</script> ", "&lt;script&gt;", "<script>"),
        ("ampersand", "&value& ", "&amp;value&amp;", "&value&"),
    ],
)
@pytest.mark.asyncio
async def test_digest_long_body_truncates_without_cutting_html_entities(
    case_name: str,
    payload: str,
    escaped_marker: str,
    raw_marker: str,
) -> None:
    del case_name
    policies = InMemoryDigestPolicyRepository()
    await policies.ensure_default_policies()
    events = EventItemService.in_memory(now_factory=lambda: NOW)
    service = DigestService(policy_repository=policies, event_repository=events.repository)
    await events.create_event(
        EventItemCreate(
            user_id=100500,
            chat_id=100500,
            scope=EventScope.PERSONAL,
            event_type=EventType.NOTE,
            title="Короткий заголовок",
            body=payload * 700,
            source="manual",
            payload_json={"raw": "must-not-render"},
            card_json={"type": "note", "title": "raw json must not render"},
        )
    )

    html = render_digest(await service.build_digest("personal_morning", now=NOW))

    _assert_safe_digest_html(html)
    assert escaped_marker in html
    assert raw_marker not in html
    assert "must-not-render" not in html
    assert "raw json must not render" not in html


@pytest.mark.asyncio
async def test_empty_digest_renders_cleanly() -> None:
    policies = InMemoryDigestPolicyRepository()
    await policies.ensure_default_policies()
    events = EventItemService.in_memory(now_factory=lambda: NOW)
    service = DigestService(policy_repository=policies, event_repository=events.repository)

    html = render_digest(await service.build_digest("personal_morning", now=NOW))

    assert "<b>🌅 Личный утренний дайджест</b>" in html
    assert "Новых событий нет." in html


def test_create_scope_helpers_use_expected_scopes() -> None:
    base = {
        "user_id": 100500,
        "chat_id": 100500,
        "event_type": EventType.NOTE,
        "title": "Заметка",
        "body": "Текст",
        "source": "test",
    }

    assert create_personal_event(**base).scope is EventScope.PERSONAL
    assert create_household_event(**base).scope is EventScope.HOUSEHOLD
    assert create_work_event(**base).scope is EventScope.WORK
    assert create_system_event(**base).scope is EventScope.SYSTEM
    assert DigestPolicyInput.default_personal().scope_filter_json == {
        "scopes": ["personal", "household"]
    }
    assert DigestPolicyInput.default_work().scope_filter_json == {"scopes": ["work"]}
