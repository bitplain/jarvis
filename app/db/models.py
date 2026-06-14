from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, ForeignKey, Index, Integer, String, Text
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
