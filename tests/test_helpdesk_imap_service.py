from dataclasses import replace

import pytest

from app.core.config import Settings
from app.services.helpdesk_imap.client import (
    HelpdeskFetchedEmail,
    HelpdeskImapAuthError,
    HelpdeskImapNetworkError,
)
from app.services.helpdesk_imap.config import HelpdeskImapConfig
from app.services.helpdesk_imap.service import HelpdeskImapService

GLPI_BODY = """
URL : https://sd.asdf.help/ticket/47513
Заголовок:
Выход нового сотрудника
Описание:
ФИО: Масленникова Дарья Александровна
Должность: специалист
Руководитель: Васильев С.
Предварительная дата выхода: 30.06.2026
Настроить доступы:
1. почта
2. CRM
"""


def _config(*, mark_seen: bool = False) -> HelpdeskImapConfig:
    return HelpdeskImapConfig.from_settings(
        Settings(
            helpdesk_imap_enabled=True,
            helpdesk_imap_host="imap.example.ru",
            helpdesk_imap_username="support@example.ru",
            helpdesk_imap_password="real-password",
            helpdesk_telegram_chat_id="-1001234567890",
            helpdesk_mark_seen=mark_seen,
        )
    )


def _message(
    *,
    message_id: str | None = "<msg-1>",
    uid: str | None = "101",
) -> HelpdeskFetchedEmail:
    return HelpdeskFetchedEmail(
        folder="INBOX",
        uid=uid,
        message_id=message_id,
        subject="[GLPI #0047513] Новая заявка",
        from_header="Service Desk <sd@asdf.help>",
        received_at=None,
        body=GLPI_BODY,
    )


class FakeHelpdeskRepository:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []
        self.notified: list[tuple[str, int, int]] = []
        self.failed: list[tuple[str, str]] = []

    async def exists(self, *, folder: str, imap_uid: str | None, message_id: str | None) -> bool:
        return any(
            (message_id and event["message_id"] == message_id)
            or (imap_uid and event["folder"] == folder and event["imap_uid"] == imap_uid)
            for event in self.events
        )

    async def create_event(self, **values: object) -> str | None:
        if await self.exists(
            folder=str(values["folder"]),
            imap_uid=values.get("imap_uid"),  # type: ignore[arg-type]
            message_id=values.get("message_id"),  # type: ignore[arg-type]
        ):
            return None
        event_id = f"event-{len(self.events) + 1}"
        self.events.append({"id": event_id, **values})
        return event_id

    async def mark_notified(
        self,
        event_id: str,
        *,
        telegram_chat_id: int,
        telegram_message_id: int,
    ) -> None:
        self.notified.append((event_id, telegram_chat_id, telegram_message_id))

    async def mark_notify_failed(self, event_id: str, *, error_code: str) -> None:
        self.failed.append((event_id, error_code))


class FakeHelpdeskClient:
    def __init__(self, messages: list[HelpdeskFetchedEmail] | None = None) -> None:
        self.messages = messages or []
        self.marked_seen: list[tuple[str, str]] = []
        self.closed = False

    async def fetch_recent(self) -> list[HelpdeskFetchedEmail]:
        return self.messages

    async def mark_seen(self, *, folder: str, uid: str) -> None:
        self.marked_seen.append((folder, uid))

    async def close(self) -> None:
        self.closed = True


class FailingHelpdeskClient(FakeHelpdeskClient):
    def __init__(self, exc: Exception) -> None:
        super().__init__([])
        self.exc = exc

    async def fetch_recent(self) -> list[HelpdeskFetchedEmail]:
        raise self.exc


class FakeNotifier:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.sent: list[object] = []

    async def send_ticket(self, *, chat_id: int, ticket: object) -> int:
        self.sent.append(ticket)
        if self.fail:
            raise RuntimeError("telegram unavailable")
        return 9001


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, *, ex: int, nx: bool = False) -> bool | None:
        del ex
        if nx and key in self.values:
            return None
        self.values[key] = value
        return True


@pytest.mark.asyncio
async def test_helpdesk_service_dedupes_same_message_id() -> None:
    repository = FakeHelpdeskRepository()
    client = FakeHelpdeskClient([_message()])
    notifier = FakeNotifier()
    service = HelpdeskImapService(
        config=_config(),
        repository=repository,  # type: ignore[arg-type]
        client=client,
        notifier=notifier,
    )

    first = await service.run_once()
    second = await service.run_once()

    assert first.processed == 1
    assert second.skipped_duplicates == 1
    assert len(notifier.sent) == 1
    assert len(repository.events) == 1


@pytest.mark.asyncio
async def test_helpdesk_service_dedupes_same_folder_uid_without_message_id() -> None:
    repository = FakeHelpdeskRepository()
    client = FakeHelpdeskClient([_message(message_id=None, uid="777")])
    notifier = FakeNotifier()
    service = HelpdeskImapService(
        config=_config(),
        repository=repository,  # type: ignore[arg-type]
        client=client,
        notifier=notifier,
    )

    await service.run_once()
    await service.run_once()

    assert len(notifier.sent) == 1
    assert len(repository.events) == 1


@pytest.mark.asyncio
async def test_helpdesk_service_telegram_failure_does_not_mark_seen() -> None:
    repository = FakeHelpdeskRepository()
    client = FakeHelpdeskClient([_message()])
    notifier = FakeNotifier(fail=True)
    service = HelpdeskImapService(
        config=_config(mark_seen=True),
        repository=repository,  # type: ignore[arg-type]
        client=client,
        notifier=notifier,
    )

    result = await service.run_once()

    assert result.failed == 1
    assert client.marked_seen == []
    assert repository.failed == [("event-1", "telegram")]


@pytest.mark.asyncio
async def test_helpdesk_service_telegram_failure_updates_status_error() -> None:
    redis = FakeRedis()
    service = HelpdeskImapService(
        config=_config(mark_seen=True),
        repository=FakeHelpdeskRepository(),  # type: ignore[arg-type]
        client=FakeHelpdeskClient([_message()]),
        notifier=FakeNotifier(fail=True),
        redis=redis,
    )

    await service.run_once()

    assert redis.values["jarvis:helpdesk_imap:last_error"] == "telegram"


@pytest.mark.asyncio
async def test_helpdesk_service_mark_seen_false_never_marks_seen() -> None:
    client = FakeHelpdeskClient([_message(uid="102")])
    service = HelpdeskImapService(
        config=_config(mark_seen=False),
        repository=FakeHelpdeskRepository(),  # type: ignore[arg-type]
        client=client,
        notifier=FakeNotifier(),
    )

    await service.run_once()

    assert client.marked_seen == []


@pytest.mark.asyncio
async def test_helpdesk_service_mark_seen_true_marks_seen_after_success() -> None:
    client = FakeHelpdeskClient([_message(uid="102")])
    service = HelpdeskImapService(
        config=_config(mark_seen=True),
        repository=FakeHelpdeskRepository(),  # type: ignore[arg-type]
        client=client,
        notifier=FakeNotifier(),
    )

    await service.run_once()

    assert client.marked_seen == [("INBOX", "102")]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exc",
    [HelpdeskImapAuthError("bad login"), HelpdeskImapNetworkError("timeout")],
)
async def test_helpdesk_service_imap_failure_does_not_crash(exc: Exception) -> None:
    service = HelpdeskImapService(
        config=_config(),
        repository=FakeHelpdeskRepository(),  # type: ignore[arg-type]
        client=FailingHelpdeskClient(exc),
        notifier=FakeNotifier(),
    )

    result = await service.run_once()

    assert result.failed == 0
    assert result.error_code in {"auth", "network"}


@pytest.mark.asyncio
async def test_helpdesk_service_skips_disabled_config() -> None:
    service = HelpdeskImapService(
        config=replace(_config(), enabled=False),
        repository=FakeHelpdeskRepository(),  # type: ignore[arg-type]
        client=FakeHelpdeskClient([_message()]),
        notifier=FakeNotifier(),
    )

    result = await service.run_once()

    assert result.status == "disabled"
    assert result.processed == 0
