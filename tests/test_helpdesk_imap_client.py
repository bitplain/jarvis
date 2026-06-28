import ssl
from typing import Any

import pytest

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


@pytest.mark.asyncio
async def test_imap_client_reads_uidvalidity_and_current_max_uid(monkeypatch: Any) -> None:
    class FakeConnection:
        def login(self, username: str, password: str) -> None:
            del username, password

        def select(self, folder: str, *, readonly: bool) -> tuple[str, list[bytes]]:
            assert folder == "INBOX"
            assert readonly is True
            return "OK", [b"3"]

        def status(self, folder: str, names: str) -> tuple[str, list[bytes]]:
            assert folder == "INBOX"
            assert names == "(UIDVALIDITY UIDNEXT)"
            return "OK", [b'INBOX (UIDVALIDITY 777 UIDNEXT 13)']

    monkeypatch.setattr(
        "app.services.helpdesk_imap.client.imaplib.IMAP4_SSL",
        lambda host, port: FakeConnection(),
    )

    snapshot = await HelpdeskImapClient(_config()).mailbox_snapshot()

    assert snapshot.folder == "INBOX"
    assert snapshot.uidvalidity == "777"
    assert snapshot.max_uid == 12


@pytest.mark.asyncio
async def test_imap_client_fetch_since_uses_uid_range_without_seen_or_delete(
    monkeypatch: Any,
) -> None:
    calls: list[tuple[str, tuple[object, ...]]] = []

    class FakeConnection:
        def login(self, username: str, password: str) -> None:
            del username, password

        def select(self, folder: str, *, readonly: bool) -> tuple[str, list[bytes]]:
            assert folder == "INBOX"
            assert readonly is True
            return "OK", [b"1"]

        def uid(self, command: str, *args: object) -> tuple[str, list[bytes | tuple[bytes, bytes]]]:
            calls.append((command, args))
            if command == "search":
                return "OK", [b"13"]
            if command == "fetch":
                raw = (
                    b"Message-ID: <msg-13>\r\n"
                    b"Subject: [GLPI #0047513] New\r\n"
                    b"From: Service Desk <sd@asdf.help>\r\n"
                    b"\r\n"
                    b"body"
                )
                return "OK", [(b"13 (BODY[] {100}", raw)]
            raise AssertionError(f"unexpected UID command: {command}")

    monkeypatch.setattr(
        "app.services.helpdesk_imap.client.imaplib.IMAP4_SSL",
        lambda host, port: FakeConnection(),
    )

    messages = await HelpdeskImapClient(_config()).fetch_since(12)

    assert [message.uid for message in messages] == ["13"]
    assert ("search", (None, "UID", "13:*")) in calls
    assert not any(command == "store" for command, _ in calls)
    assert not any(command == "delete" for command, _ in calls)
