import ssl
from typing import Any

from app.core.config import Settings
from app.services.helpdesk_imap.client import HelpdeskImapClient
from app.services.helpdesk_imap.config import HelpdeskImapConfig


def _config() -> HelpdeskImapConfig:
    return HelpdeskImapConfig.from_settings(
        Settings(
            helpdesk_imap_enabled=True,
            helpdesk_imap_host="imap.example.ru",
            helpdesk_imap_username="support@example.ru",
            helpdesk_imap_password="test-password",
            helpdesk_telegram_chat_id="-1001234567890",
        )
    )


def test_imap_ssl_retries_legacy_dh_context(monkeypatch: Any) -> None:
    calls: list[ssl.SSLContext | None] = []

    class FakeConnection:
        def login(self, username: str, password: str) -> None:
            assert username == "support@example.ru"
            assert password == "test-password"

        def select(self, folder: str, *, readonly: bool) -> None:
            assert folder == "INBOX"
            assert readonly is True

    def fake_imap4_ssl(host: str, port: int, **kwargs: object) -> FakeConnection:
        assert host == "imap.example.ru"
        assert port == 993
        context = kwargs.get("ssl_context")
        calls.append(context if isinstance(context, ssl.SSLContext) else None)
        if len(calls) == 1:
            raise ssl.SSLError("[SSL: DH_KEY_TOO_SMALL] dh key too small")
        return FakeConnection()

    monkeypatch.setattr("app.services.helpdesk_imap.client.imaplib.IMAP4_SSL", fake_imap4_ssl)

    connection = HelpdeskImapClient(_config())._connect()

    assert isinstance(connection, FakeConnection)
    assert len(calls) == 2
    assert calls[0] is None
    assert isinstance(calls[1], ssl.SSLContext)
