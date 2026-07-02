from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class MessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class LLMRequestStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class GuestMessageStatus(StrEnum):
    RECEIVED = "received"
    ANSWERED = "answered"
    FAILED = "failed"
    IGNORED = "ignored"


class BusinessConnectionStatus(StrEnum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    IGNORED = "ignored"
    FAILED = "failed"


class BusinessMessageDirection(StrEnum):
    INCOMING = "incoming"
    OUTGOING = "outgoing"
    EDITED = "edited"
    DELETED = "deleted"


class BusinessMessageStatus(StrEnum):
    RECEIVED = "received"
    IGNORED = "ignored"
    QUEUED = "queued"
    ANSWERED = "answered"
    FAILED = "failed"
    DELETED = "deleted"
    EDITED = "edited"


class TelegramAccessEntryType(StrEnum):
    USER = "user"
    GROUP = "group"


class ShoppingScopeType(StrEnum):
    PRIVATE = "private"
    GROUP = "group"


class ShoppingItemStatus(StrEnum):
    ACTIVE = "active"
    DONE = "done"


class ReminderScopeType(StrEnum):
    PRIVATE = "private"
    GROUP = "group"


class ReminderStatus(StrEnum):
    SCHEDULED = "scheduled"
    SENT = "sent"
    CANCELLED = "cancelled"


class EventScope(StrEnum):
    PERSONAL = "personal"
    HOUSEHOLD = "household"
    WORK = "work"
    SYSTEM = "system"


class EventStatus(StrEnum):
    NEW = "new"
    SEEN = "seen"
    DONE = "done"
    SNOOZED = "snoozed"
    ARCHIVED = "archived"
    FAILED = "failed"


class EventPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class EventType(StrEnum):
    REMINDER = "reminder"
    NOTE = "note"
    SHOPPING = "shopping"
    HELPDESK_TICKET = "helpdesk_ticket"
    WHOOP_SLEEP = "whoop_sleep"
    SYSTEM_ALERT = "system_alert"
    DIGEST_ITEM = "digest_item"


class HouseholdMemoryStatus(StrEnum):
    ACTIVE = "active"
    DELETED = "deleted"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(255))
    first_name: Mapped[str | None] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Chat(Base):
    __tablename__ = "chats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    chat_type: Mapped[str] = mapped_column(String(64))
    title: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    telegram_message_id: Mapped[int | None] = mapped_column(Integer)
    role: Mapped[MessageRole] = mapped_column(Enum(MessageRole, name="message_role"))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LLMRequest(Base):
    __tablename__ = "llm_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(255))
    status: Mapped[LLMRequestStatus] = mapped_column(
        Enum(LLMRequestStatus, name="llm_request_status"),
        default=LLMRequestStatus.QUEUED,
    )
    error_code: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    responses: Mapped[list["LLMResponseRecord"]] = relationship(back_populates="request")


class LLMResponseRecord(Base):
    __tablename__ = "llm_responses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("llm_requests.id"))
    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    request: Mapped[LLMRequest] = relationship(back_populates="responses")


class ProviderModelCache(Base):
    __tablename__ = "provider_model_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), index=True)
    models: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RuntimeSetting(Base):
    __tablename__ = "runtime_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )
    updated_by_telegram_id: Mapped[int | None] = mapped_column(BigInteger)


class EventItem(Base):
    __tablename__ = "event_items"
    __table_args__ = (
        CheckConstraint(
            "scope IN ('personal', 'household', 'work', 'system')",
            name="ck_event_items_scope",
        ),
        CheckConstraint(
            "status IN ('new', 'seen', 'done', 'snoozed', 'archived', 'failed')",
            name="ck_event_items_status",
        ),
        CheckConstraint(
            "priority IN ('low', 'normal', 'high', 'critical')",
            name="ck_event_items_priority",
        ),
        CheckConstraint(
            (
                "event_type IN ('reminder', 'note', 'shopping', 'helpdesk_ticket', "
                "'whoop_sleep', 'system_alert', 'digest_item')"
            ),
            name="ck_event_items_event_type",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    chat_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default=EventPriority.NORMAL)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=EventStatus.NEW)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    card_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )


class DigestPolicy(Base):
    __tablename__ = "digest_policies"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    scope_filter_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    send_time: Mapped[str] = mapped_column(Text, nullable=False)
    timezone: Mapped[str] = mapped_column(Text, nullable=False, default="Europe/Moscow")
    target_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    last_sent_date: Mapped[date | None] = mapped_column(Date)
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )


class WebSearchCache(Base):
    __tablename__ = "web_search_cache"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "query_hash",
            name="uq_web_search_cache_provider_query_hash",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    query_hash: Mapped[str] = mapped_column(Text, nullable=False)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    results_json: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class HelpdeskEmailEvent(Base):
    __tablename__ = "helpdesk_email_events"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    message_id: Mapped[str | None] = mapped_column(Text)
    imap_uid: Mapped[str | None] = mapped_column(Text)
    folder: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    from_email_masked: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    glpi_ticket_id: Mapped[str | None] = mapped_column(Text)
    ticket_url: Mapped[str | None] = mapped_column(Text)
    event_type: Mapped[str | None] = mapped_column(Text)
    parse_status: Mapped[str] = mapped_column(Text, nullable=False)
    notify_status: Mapped[str] = mapped_column(Text, nullable=False)
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger)
    error_code: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )


class HelpdeskTicketWorkItem(Base):
    __tablename__ = "helpdesk_ticket_work_items"
    __table_args__ = (
        UniqueConstraint(
            "glpi_ticket_id",
            "telegram_chat_id",
            name="uq_helpdesk_ticket_work_items_ticket_chat",
        ),
        CheckConstraint(
            "status IN ('waiting_ack', 'in_work', 'done', 'dismissed')",
            name="ck_helpdesk_ticket_work_items_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    glpi_ticket_id: Mapped[str] = mapped_column(Text, nullable=False)
    latest_event_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("helpdesk_email_events.id", ondelete="SET NULL"),
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    assigned_by_user_id: Mapped[int | None] = mapped_column(BigInteger)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_reminder_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_reminded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reminder_interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )


class HelpdeskVacationState(Base):
    __tablename__ = "helpdesk_vacation_state"
    __table_args__ = (UniqueConstraint("scope", name="uq_helpdesk_vacation_state_scope"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    scope: Mapped[str] = mapped_column(Text, nullable=False, default="default")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enabled_by_user_id: Mapped[int | None] = mapped_column(BigInteger)
    disabled_by_user_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )


class HelpdeskImapMailboxState(Base):
    __tablename__ = "helpdesk_imap_mailbox_state"
    __table_args__ = (UniqueConstraint("folder", name="uq_helpdesk_imap_mailbox_state_folder"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    folder: Mapped[str] = mapped_column(Text, nullable=False)
    uidvalidity: Mapped[str | None] = mapped_column(Text)
    last_seen_uid: Mapped[int | None] = mapped_column(BigInteger)
    baseline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )


class HouseholdMemoryEntry(Base):
    __tablename__ = "household_memory_entries"
    __table_args__ = (
        CheckConstraint(
            "scope_type IN ('private', 'group')",
            name="ck_household_memory_entries_scope_type",
        ),
        CheckConstraint(
            "status IN ('active', 'deleted')",
            name="ck_household_memory_entries_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False)
    scope_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_by_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TelegramAccessEntry(Base):
    __tablename__ = "telegram_access_entries"
    __table_args__ = (
        CheckConstraint(
            "entry_type IN ('user', 'group')",
            name="ck_telegram_access_entries_entry_type",
        ),
        UniqueConstraint(
            "entry_type",
            "telegram_id",
            name="uq_telegram_access_entries_entry_type_telegram_id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entry_type: Mapped[str] = mapped_column(String(16), nullable=False)
    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    label: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )


class ShoppingList(Base):
    __tablename__ = "shopping_lists"
    __table_args__ = (
        CheckConstraint(
            "scope_type IN ('private', 'group')",
            name="ck_shopping_lists_scope_type",
        ),
        UniqueConstraint(
            "scope_type",
            "scope_chat_id",
            name="uq_shopping_lists_scope",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False)
    scope_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    owner_user_id: Mapped[int | None] = mapped_column(BigInteger)
    title: Mapped[str] = mapped_column(Text, default="Список покупок")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )
    items: Mapped[list["ShoppingListItem"]] = relationship(
        back_populates="shopping_list",
        cascade="all, delete-orphan",
    )


class ShoppingListItem(Base):
    __tablename__ = "shopping_list_items"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'done')",
            name="ck_shopping_list_items_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    list_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("shopping_lists.id", ondelete="CASCADE"),
        nullable=False,
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    unit: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_by_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    shopping_list: Mapped[ShoppingList] = relationship(back_populates="items")


class Reminder(Base):
    __tablename__ = "reminders"
    __table_args__ = (
        CheckConstraint(
            "scope_type IN ('private', 'group')",
            name="ck_reminders_scope_type",
        ),
        CheckConstraint(
            "status IN ('scheduled', 'sent', 'cancelled')",
            name="ck_reminders_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    remind_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="scheduled")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DailyBriefSettings(Base):
    __tablename__ = "daily_brief_settings"
    __table_args__ = (
        CheckConstraint(
            "scope_type IN ('private', 'group')",
            name="ck_daily_brief_settings_scope_type",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int | None] = mapped_column(BigInteger)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    send_time: Mapped[str] = mapped_column(String(5), nullable=False, default="09:00")
    timezone: Mapped[str] = mapped_column(Text, nullable=False, default="Europe/Moscow")
    last_sent_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )


class BusinessConnectionStub(Base):
    __tablename__ = "business_connections_stub"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    update_type: Mapped[str] = mapped_column(String(128))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BusinessConnection(Base):
    __tablename__ = "business_connections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_connection_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    business_user_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    user_chat_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    can_reply: Mapped[bool] = mapped_column(Boolean, default=False)
    can_read_messages: Mapped[bool] = mapped_column(Boolean, default=False)
    rights_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[BusinessConnectionStatus] = mapped_column(
        Enum(
            BusinessConnectionStatus,
            name="business_connection_status",
            values_callable=lambda enum_class: [status.value for status in enum_class],
        ),
        default=BusinessConnectionStatus.IGNORED,
    )


class BusinessMessage(Base):
    __tablename__ = "business_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_connection_id: Mapped[str] = mapped_column(String(255), index=True)
    telegram_message_id: Mapped[int] = mapped_column(Integer, index=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    from_user_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    direction: Mapped[BusinessMessageDirection] = mapped_column(
        Enum(
            BusinessMessageDirection,
            name="business_message_direction",
            values_callable=lambda enum_class: [direction.value for direction in enum_class],
        )
    )
    message_text: Mapped[str | None] = mapped_column(Text)
    reply_to_message_id: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[BusinessMessageStatus] = mapped_column(
        Enum(
            BusinessMessageStatus,
            name="business_message_status",
            values_callable=lambda enum_class: [status.value for status in enum_class],
        ),
        default=BusinessMessageStatus.RECEIVED,
    )
    provider: Mapped[str | None] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(255))
    response_text: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GuestMessageRecord(Base):
    __tablename__ = "guest_messages_stub"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    telegram_update_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    guest_query_id_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    caller_user_id_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    caller_chat_id_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    request_text: Mapped[str] = mapped_column(Text, default="")
    replied_text: Mapped[str | None] = mapped_column(Text)
    response_text: Mapped[str | None] = mapped_column(Text)
    provider: Mapped[str | None] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[GuestMessageStatus] = mapped_column(
        Enum(
            GuestMessageStatus,
            name="guest_message_status",
            values_callable=lambda enum_class: [status.value for status in enum_class],
        ),
        default=GuestMessageStatus.RECEIVED,
    )
    error_code: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


GuestMessageStub = GuestMessageRecord


Index("ix_messages_chat_created", Message.chat_id, Message.created_at)
Index(
    "ix_business_messages_connection_chat_created",
    BusinessMessage.business_connection_id,
    BusinessMessage.chat_id,
    BusinessMessage.created_at,
)
Index(
    "ix_business_messages_lookup",
    BusinessMessage.business_connection_id,
    BusinessMessage.chat_id,
    BusinessMessage.telegram_message_id,
)
Index("ix_shopping_list_items_list_status", ShoppingListItem.list_id, ShoppingListItem.status)
Index("ix_shopping_list_items_list_created", ShoppingListItem.list_id, ShoppingListItem.created_at)
Index("ix_reminders_status_remind_at", Reminder.status, Reminder.remind_at)
Index("ix_reminders_chat_status_remind_at", Reminder.chat_id, Reminder.status, Reminder.remind_at)
Index("ix_reminders_user_status_remind_at", Reminder.user_id, Reminder.status, Reminder.remind_at)
Index(
    "ix_household_memory_scope_status",
    HouseholdMemoryEntry.scope_type,
    HouseholdMemoryEntry.scope_chat_id,
    HouseholdMemoryEntry.status,
)
Index(
    "ix_household_memory_created_by_status",
    HouseholdMemoryEntry.created_by_user_id,
    HouseholdMemoryEntry.status,
)
Index(
    "ix_event_items_scope_status_priority_due",
    EventItem.scope,
    EventItem.status,
    EventItem.priority,
    EventItem.due_at,
)
Index("ix_event_items_user_scope_status", EventItem.user_id, EventItem.scope, EventItem.status)
Index("ix_event_items_chat_scope_status", EventItem.chat_id, EventItem.scope, EventItem.status)
Index("ix_event_items_created_at", EventItem.created_at)
Index(
    "uq_daily_brief_settings_private_scope",
    DailyBriefSettings.scope_type,
    DailyBriefSettings.chat_id,
    DailyBriefSettings.user_id,
    unique=True,
    postgresql_where=DailyBriefSettings.user_id.is_not(None),
)
Index(
    "uq_daily_brief_settings_group_scope",
    DailyBriefSettings.scope_type,
    DailyBriefSettings.chat_id,
    unique=True,
    postgresql_where=DailyBriefSettings.user_id.is_(None),
)
Index("ix_web_search_cache_expires_at", WebSearchCache.expires_at)
Index(
    "uq_helpdesk_email_events_message_id",
    HelpdeskEmailEvent.message_id,
    unique=True,
    postgresql_where=HelpdeskEmailEvent.message_id.is_not(None),
)
Index(
    "uq_helpdesk_email_events_folder_imap_uid",
    HelpdeskEmailEvent.folder,
    HelpdeskEmailEvent.imap_uid,
    unique=True,
    postgresql_where=HelpdeskEmailEvent.imap_uid.is_not(None),
)
Index("ix_helpdesk_email_events_created_at", HelpdeskEmailEvent.created_at)
Index("ix_helpdesk_email_events_notify_status", HelpdeskEmailEvent.notify_status)
Index("ix_helpdesk_email_events_glpi_ticket_id", HelpdeskEmailEvent.glpi_ticket_id)
Index(
    "ix_helpdesk_ticket_work_items_status_next",
    HelpdeskTicketWorkItem.status,
    HelpdeskTicketWorkItem.next_reminder_at,
)
Index(
    "ix_helpdesk_ticket_work_items_chat_status",
    HelpdeskTicketWorkItem.telegram_chat_id,
    HelpdeskTicketWorkItem.status,
)
Index("ix_helpdesk_imap_mailbox_state_updated_at", HelpdeskImapMailboxState.updated_at)
Index("ix_helpdesk_vacation_state_updated_at", HelpdeskVacationState.updated_at)
