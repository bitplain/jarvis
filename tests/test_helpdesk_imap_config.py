import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.services.helpdesk_imap.config import HelpdeskImapConfig, mask_email


def test_helpdesk_imap_disabled_by_default_and_password_not_in_repr() -> None:
    settings = Settings()

    config = HelpdeskImapConfig.from_settings(settings)

    assert config.enabled is False
    assert config.configured is False
    assert config.missing_required == ()
    assert "password" not in repr(config).lower()


def test_helpdesk_imap_enabled_incomplete_config_is_safe_to_report() -> None:
    settings = Settings(
        helpdesk_imap_enabled=True,
        helpdesk_imap_host="imap.example.ru",
        helpdesk_imap_username="support@example.ru",
        helpdesk_imap_password="real-password",
    )

    config = HelpdeskImapConfig.from_settings(settings)

    assert config.enabled is True
    assert config.configured is False
    assert config.missing_required == ("helpdesk_telegram_chat_id",)
    assert config.safe_username == "s***t@example.ru"
    assert config.safe_summary() == {
        "enabled": "yes",
        "configured": "no",
        "host": "configured",
        "username": "s***t@example.ru",
        "folder": "INBOX",
        "mark_seen": "no",
    }
    assert "real-password" not in repr(config)
    assert "support@example.ru" not in repr(config)


def test_helpdesk_imap_bool_and_int_env_values_are_parsed() -> None:
    settings = Settings(
        helpdesk_imap_enabled="true",
        helpdesk_imap_ssl="false",
        helpdesk_imap_port="143",
        helpdesk_imap_poll_interval_seconds="60",
        helpdesk_telegram_chat_id="-1001234567890",
    )

    config = HelpdeskImapConfig.from_settings(settings)

    assert config.enabled is True
    assert config.ssl is False
    assert config.port == 143
    assert config.poll_interval_seconds == 60
    assert config.telegram_chat_id == -1001234567890


def test_helpdesk_imap_invalid_port_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(helpdesk_imap_port=70000)


@pytest.mark.parametrize(
    ("value", "masked"),
    [
        ("sd@asdf.help", "s***d@asdf.help"),
        ("a@domain.ru", "a***@domain.ru"),
        ("plain-user", "p***r"),
        ("", "missing"),
    ],
)
def test_mask_email(value: str, masked: str) -> None:
    assert mask_email(value) == masked
