from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
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
