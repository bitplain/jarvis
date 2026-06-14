from app.db.models import (
    BusinessConnection,
    BusinessConnectionStatus,
    BusinessMessage,
    BusinessMessageDirection,
    BusinessMessageStatus,
)


def test_business_connection_model_has_guard_fields() -> None:
    columns = BusinessConnection.__table__.columns

    assert "business_connection_id" in columns
    assert "business_user_id" in columns
    assert "is_enabled" in columns
    assert "can_reply" in columns
    assert "rights_json" in columns
    assert "disabled_at" in columns
    assert BusinessConnectionStatus.ENABLED.value == "enabled"
    assert BusinessConnectionStatus.IGNORED.value == "ignored"


def test_business_message_model_has_reply_audit_fields() -> None:
    columns = BusinessMessage.__table__.columns

    assert "business_connection_id" in columns
    assert "telegram_message_id" in columns
    assert "direction" in columns
    assert "provider" in columns
    assert "model" in columns
    assert "response_text" in columns
    assert BusinessMessageDirection.INCOMING.value == "incoming"
    assert BusinessMessageStatus.ANSWERED.value == "answered"
    assert BusinessMessageStatus.DELETED.value == "deleted"
