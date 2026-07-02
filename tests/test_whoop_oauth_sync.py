from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.bot.routers import commands
from app.core.config import Settings
from app.db.models import WhoopCycleRecord, WhoopIntegration, WhoopRecoveryRecord, WhoopSleepRecord
from app.main import create_app
from app.services.secret_cipher import SecretCipher
from app.services.whoop_client import (
    WHOOP_AUTHORIZATION_URL,
    WHOOP_SCOPES,
    WHOOP_TOKEN_URL,
    WhoopClientError,
    WhoopRateLimitError,
    WhoopServerError,
    WhoopUnauthorizedError,
    build_authorization_url,
    exchange_code_for_tokens,
    get_sleep_collection,
    refresh_access_token,
)
from app.services.whoop_sync import WhoopSyncService
from app.workers import jobs
from app.workers.arq_settings import WorkerSettings

NOW = datetime(2026, 7, 2, 6, 0, tzinfo=UTC)
LOOKBACK_START = NOW - timedelta(hours=48)


def test_whoop_config_defaults_are_disabled_and_safe() -> None:
    settings = Settings()

    assert settings.whoop_enabled is False
    assert settings.whoop_client_id == ""
    assert settings.whoop_client_secret == ""
    assert settings.whoop_redirect_uri == ""
    assert settings.whoop_token_encryption_key == ""
    assert settings.whoop_configured is False


def test_whoop_config_requires_enabled_client_redirect_and_cipher_key() -> None:
    missing_secret = Settings(
        whoop_enabled=True,
        whoop_client_id="client-id",
        whoop_redirect_uri="https://example.com/integrations/whoop/oauth/callback",
        whoop_token_encryption_key=SecretCipher.generate_key(),
    )
    configured = Settings(
        whoop_enabled=True,
        whoop_client_id="client-id",
        whoop_client_secret="client-secret",
        whoop_redirect_uri="https://example.com/integrations/whoop/oauth/callback",
        whoop_token_encryption_key=SecretCipher.generate_key(),
    )

    assert missing_secret.whoop_configured is False
    assert configured.whoop_configured is True


def test_whoop_models_expose_raw_sync_tables_and_constraints() -> None:
    integration_columns = set(WhoopIntegration.__table__.columns.keys())
    sleep_columns = set(WhoopSleepRecord.__table__.columns.keys())
    recovery_columns = set(WhoopRecoveryRecord.__table__.columns.keys())
    cycle_columns = set(WhoopCycleRecord.__table__.columns.keys())

    assert WhoopIntegration.__tablename__ == "whoop_integrations"
    assert {
        "id",
        "user_id",
        "telegram_user_id",
        "status",
        "scope",
        "access_token_encrypted",
        "refresh_token_encrypted",
        "expires_at",
        "whoop_user_id",
        "profile_json",
        "last_sync_at",
        "last_error",
        "created_at",
        "updated_at",
    } <= integration_columns
    assert {
        "id",
        "integration_id",
        "user_id",
        "whoop_sleep_id",
        "cycle_id",
        "start_at",
        "end_at",
        "timezone_offset",
        "nap",
        "score_state",
        "raw_json",
        "created_at",
        "updated_at",
    } <= sleep_columns
    assert {
        "id",
        "integration_id",
        "user_id",
        "cycle_id",
        "score_state",
        "recovery_score",
        "hrv_rmssd_milli",
        "resting_heart_rate",
        "raw_json",
        "created_at",
        "updated_at",
    } <= recovery_columns
    assert {
        "id",
        "integration_id",
        "user_id",
        "cycle_id",
        "start_at",
        "end_at",
        "timezone_offset",
        "score_state",
        "raw_json",
        "created_at",
        "updated_at",
    } <= cycle_columns


def test_secret_cipher_round_trips_without_plaintext_storage() -> None:
    cipher = SecretCipher(SecretCipher.generate_key())

    encrypted = cipher.encrypt("whoop-access-token")

    assert encrypted != "whoop-access-token"
    assert "whoop-access-token" not in encrypted
    assert cipher.decrypt(encrypted) == "whoop-access-token"


def test_whoop_settings_ui_shows_not_configured_without_secrets() -> None:
    text = commands.render_whoop_settings_text(
        enabled=True,
        configured=False,
        status="not_connected",
        last_sync_at=None,
        last_error=None,
        scope="",
    )
    keyboard = commands.build_whoop_settings_keyboard(configured=False, connected=False)

    assert "WHOOP" in commands.render_settings_home_text()
    assert "Статус: не настроен" in text
    assert "client-secret" not in text
    assert any(
        button.callback_data == commands.SETTINGS_CALLBACK_WHOOP_CONNECT
        for row in keyboard.inline_keyboard
        for button in row
    )


def test_build_authorization_url_uses_official_url_scopes_and_state() -> None:
    url = build_authorization_url(
        client_id="client-id",
        redirect_uri="https://jarvis.example.com/integrations/whoop/oauth/callback",
        state="state-123",
    )
    parsed = urlparse(url)
    params = parse_qs(parsed.query)

    assert url.startswith(WHOOP_AUTHORIZATION_URL)
    assert params["client_id"] == ["client-id"]
    assert params["redirect_uri"] == [
        "https://jarvis.example.com/integrations/whoop/oauth/callback"
    ]
    assert params["response_type"] == ["code"]
    assert params["state"] == ["state-123"]
    assert params["scope"] == [" ".join(WHOOP_SCOPES)]
    assert WHOOP_SCOPES == (
        "offline",
        "read:profile",
        "read:sleep",
        "read:recovery",
        "read:cycles",
    )


@pytest.mark.asyncio
async def test_whoop_client_exchanges_refreshes_and_handles_rate_limits() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if str(request.url) == WHOOP_TOKEN_URL:
            body = request.content.decode()
            if "grant_type=authorization_code" in body:
                return httpx.Response(
                    200,
                    json={
                        "access_token": "access-1",
                        "refresh_token": "refresh-1",
                        "expires_in": 3600,
                        "scope": "offline read:profile read:sleep read:recovery read:cycles",
                        "token_type": "bearer",
                    },
                )
            if "grant_type=refresh_token" in body:
                return httpx.Response(
                    200,
                    json={
                        "access_token": "access-2",
                        "refresh_token": "refresh-2",
                        "expires_in": 3600,
                        "scope": "offline read:profile read:sleep read:recovery read:cycles",
                        "token_type": "bearer",
                    },
                )
        if request.url.path == "/developer/v2/activity/sleep":
            if request.url.params.get("limit") == "429":
                return httpx.Response(429, json={"error": "too many"})
            if request.url.params.get("limit") == "500":
                return httpx.Response(500, json={"error": "server"})
            return httpx.Response(
                200,
                json={
                    "records": [
                        {
                            "id": "sleep-1",
                            "cycle_id": 123,
                            "user_id": 42,
                            "start": "2026-07-01T21:00:00Z",
                            "end": "2026-07-02T05:00:00Z",
                            "timezone_offset": "+03:00",
                            "nap": False,
                            "score_state": "PENDING_SCORE",
                        }
                    ],
                    "next_token": None,
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    settings = Settings(
        whoop_client_id="client-id",
        whoop_client_secret="client-secret",
        whoop_redirect_uri="https://jarvis.example.com/integrations/whoop/oauth/callback",
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://api.prod.whoop.com",
    ) as client:
        exchanged = await exchange_code_for_tokens(
            code="code-1",
            settings=settings,
            http_client=client,
        )
        refreshed = await refresh_access_token(
            refresh_token="refresh-1",
            settings=settings,
            http_client=client,
        )
        sleeps = await get_sleep_collection(
            access_token="access-2",
            start=LOOKBACK_START,
            end=NOW,
            http_client=client,
        )
        with pytest.raises(WhoopRateLimitError):
            await get_sleep_collection(
                access_token="access-2",
                start=LOOKBACK_START,
                end=NOW,
                http_client=client,
                limit=429,
            )
        with pytest.raises(WhoopServerError):
            await get_sleep_collection(
                access_token="access-2",
                start=LOOKBACK_START,
                end=NOW,
                http_client=client,
                limit=500,
            )

    assert exchanged.access_token == "access-1"
    assert refreshed.access_token == "access-2"
    assert refreshed.refresh_token == "refresh-2"
    assert sleeps[0]["score_state"] == "PENDING_SCORE"
    assert all("Authorization" not in str(request.content) for request in requests)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expirations: dict[str, int] = {}
        self.deleted: list[str] = []

    async def set(self, key: str, value: str, *, ex: int, nx: bool = False) -> bool | None:
        if nx and key in self.values:
            return None
        self.values[key] = value
        self.expirations[key] = ex
        return True

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def getdel(self, key: str) -> str | None:
        return self.values.pop(key, None)

    async def delete(self, key: str) -> None:
        self.deleted.append(key)
        self.values.pop(key, None)


class RaceyRedis(FakeRedis):
    async def get(self, key: str) -> str | None:
        await asyncio.sleep(0)
        return self.values.get(key)

    async def delete(self, key: str) -> None:
        await asyncio.sleep(0)
        await super().delete(key)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "key",
    [
        "whoop:oauth:start:start-token",
        "whoop:oauth:state:state-token",
    ],
)
async def test_whoop_oauth_token_consume_is_atomic_under_parallel_access(key: str) -> None:
    redis = RaceyRedis()
    redis.values[key] = "100500"

    from app.api.routes_whoop import _consume_redis_value

    results = await asyncio.gather(
        _consume_redis_value(redis, key),
        _consume_redis_value(redis, key),
    )

    assert results.count("100500") == 1
    assert results.count(None) == 1


@pytest.mark.asyncio
async def test_whoop_oauth_start_uses_one_time_token_and_stores_state() -> None:
    redis = FakeRedis()
    redis.values["whoop:oauth:start:start-token"] = "100500"
    app = create_app(
        settings=Settings(
            whoop_enabled=True,
            whoop_client_id="client-id",
            whoop_client_secret="client-secret",
            whoop_redirect_uri="https://jarvis.example.com/integrations/whoop/oauth/callback",
            whoop_token_encryption_key=SecretCipher.generate_key(),
            redis_url="redis://unused:6379/0",
        )
    )
    app.state.redis_pool = redis

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/integrations/whoop/oauth/start",
            params={"connect_token": "start-token"},
            follow_redirects=False,
        )

    assert response.status_code == 307
    location = response.headers["location"]
    assert location.startswith(WHOOP_AUTHORIZATION_URL)
    state_keys = [key for key in redis.values if key.startswith("whoop:oauth:state:")]
    assert len(state_keys) == 1
    assert redis.values[state_keys[0]] == "100500"
    assert redis.expirations[state_keys[0]] == 600
    assert "whoop:oauth:start:start-token" not in redis.values


@pytest.mark.asyncio
async def test_whoop_oauth_callback_rejects_bad_state_and_success_hides_tokens() -> None:
    redis = FakeRedis()
    redis.values["whoop:oauth:state:good-state"] = "100500"
    redis.expirations["whoop:oauth:state:good-state"] = 600
    app = create_app(
        settings=Settings(
            whoop_enabled=True,
            whoop_client_id="client-id",
            whoop_client_secret="client-secret",
            whoop_redirect_uri="https://jarvis.example.com/integrations/whoop/oauth/callback",
            whoop_token_encryption_key=SecretCipher.generate_key(),
            redis_url="redis://unused:6379/0",
        )
    )
    app.state.redis_pool = redis
    app.state.whoop_oauth_connector = SimpleNamespace(
        complete=lambda **kwargs: SimpleNamespace(
            status="connected",
            kwargs=kwargs,
        )
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        bad = await client.get(
            "/integrations/whoop/oauth/callback",
            params={"state": "bad-state", "code": "secret-code"},
        )
        good = await client.get(
            "/integrations/whoop/oauth/callback",
            params={"state": "good-state", "code": "secret-code"},
        )
        repeated = await client.get(
            "/integrations/whoop/oauth/callback",
            params={"state": "good-state", "code": "secret-code"},
        )
        missing = await client.get(
            "/integrations/whoop/oauth/callback",
            params={"state": "missing-state", "code": "secret-code"},
        )

    assert bad.status_code == 400
    assert "secret-code" not in bad.text
    assert good.status_code == 200
    assert "WHOOP подключён" in good.text
    assert "secret-code" not in good.text
    assert repeated.status_code == 400
    assert missing.status_code == 400
    assert "whoop:oauth:state:good-state" not in redis.values


class FakeWhoopRepository:
    def __init__(self, cipher: SecretCipher) -> None:
        self.integration = SimpleNamespace(
            id="integration-1",
            user_id=100500,
            telegram_user_id=100500,
            status="connected",
            scope="offline read:profile read:sleep read:recovery read:cycles",
            access_token_encrypted=cipher.encrypt("expired-access"),
            refresh_token_encrypted=cipher.encrypt("refresh-1"),
            expires_at=NOW - timedelta(minutes=1),
            whoop_user_id=None,
            profile_json=None,
            last_sync_at=None,
            last_error=None,
        )
        self.updated_tokens: list[tuple[str, str, datetime, str]] = []
        self.profile: dict[str, Any] | None = None
        self.sleep_records: list[dict[str, Any]] = []
        self.recovery_records: list[dict[str, Any]] = []
        self.cycle_records: list[dict[str, Any]] = []
        self.successes: list[datetime] = []
        self.errors: list[str] = []

    async def get_connected_for_update(self, integration_id: str) -> object | None:
        assert integration_id == "integration-1"
        return self.integration

    async def update_tokens(
        self,
        integration_id: str,
        *,
        access_token_encrypted: str,
        refresh_token_encrypted: str,
        expires_at: datetime,
        scope: str,
    ) -> None:
        self.updated_tokens.append(
            (access_token_encrypted, refresh_token_encrypted, expires_at, scope)
        )
        self.integration.access_token_encrypted = access_token_encrypted
        self.integration.refresh_token_encrypted = refresh_token_encrypted
        self.integration.expires_at = expires_at
        self.integration.scope = scope

    async def update_profile(
        self,
        integration_id: str,
        *,
        whoop_user_id: int | None,
        profile_json: dict[str, Any],
    ) -> None:
        del integration_id, whoop_user_id
        self.profile = profile_json

    async def upsert_sleep_record(self, integration_id: str, record: dict[str, Any]) -> None:
        del integration_id
        self.sleep_records = [
            existing for existing in self.sleep_records if existing["id"] != record["id"]
        ]
        self.sleep_records.append(record)

    async def upsert_recovery_record(self, integration_id: str, record: dict[str, Any]) -> None:
        del integration_id
        self.recovery_records = [
            existing
            for existing in self.recovery_records
            if existing["cycle_id"] != record["cycle_id"]
        ]
        self.recovery_records.append(record)

    async def upsert_cycle_record(self, integration_id: str, record: dict[str, Any]) -> None:
        del integration_id
        self.cycle_records = [
            existing for existing in self.cycle_records if existing["id"] != record["id"]
        ]
        self.cycle_records.append(record)

    async def mark_sync_success(self, integration_id: str, *, synced_at: datetime) -> None:
        del integration_id
        self.successes.append(synced_at)
        self.integration.last_sync_at = synced_at
        self.integration.last_error = None

    async def mark_sync_error(self, integration_id: str, *, error_code: str) -> None:
        del integration_id
        self.errors.append(error_code)
        self.integration.last_error = error_code


class FakeWhoopClient:
    async def refresh_access_token(self, **kwargs: Any) -> object:
        assert kwargs["refresh_token"] == "refresh-1"
        return SimpleNamespace(
            access_token="access-2",
            refresh_token="refresh-2",
            expires_in=3600,
            scope="offline read:profile read:sleep read:recovery read:cycles",
        )

    async def get_profile(self, **kwargs: Any) -> dict[str, Any]:
        assert kwargs["access_token"] == "access-2"
        return {"user_id": 42, "email": "private@example.com"}

    async def get_sleep_collection(self, **kwargs: Any) -> list[dict[str, Any]]:
        assert kwargs["access_token"] == "access-2"
        return [
            {
                "id": "sleep-pending",
                "cycle_id": 101,
                "user_id": 42,
                "start": "2026-07-01T21:00:00Z",
                "end": "2026-07-02T05:00:00Z",
                "timezone_offset": "+03:00",
                "nap": False,
                "score_state": "PENDING_SCORE",
            },
            {
                "id": "sleep-unscorable",
                "cycle_id": 102,
                "user_id": 42,
                "start": "2026-06-30T21:00:00Z",
                "end": "2026-07-01T05:00:00Z",
                "timezone_offset": "+03:00",
                "nap": False,
                "score_state": "UNSCORABLE",
            },
        ]

    async def get_recovery_collection(self, **kwargs: Any) -> list[dict[str, Any]]:
        assert kwargs["access_token"] == "access-2"
        return [
            {
                "cycle_id": 101,
                "user_id": 42,
                "score_state": "SCORED",
                "score": {
                    "recovery_score": 77,
                    "hrv_rmssd_milli": 33.5,
                    "resting_heart_rate": 61,
                },
            }
        ]

    async def get_cycle_collection(self, **kwargs: Any) -> list[dict[str, Any]]:
        assert kwargs["access_token"] == "access-2"
        return [
            {
                "id": 101,
                "user_id": 42,
                "start": "2026-07-01T05:00:00Z",
                "end": "2026-07-02T05:00:00Z",
                "timezone_offset": "+03:00",
                "score_state": "SCORED",
            }
        ]


class UnauthorizedThenSuccessWhoopClient:
    def __init__(self) -> None:
        self.refresh_calls = 0
        self.profile_calls: list[str] = []

    async def refresh_access_token(self, **kwargs: Any) -> object:
        assert kwargs["refresh_token"] == "refresh-1"
        self.refresh_calls += 1
        return SimpleNamespace(
            access_token="access-2",
            refresh_token="refresh-2",
            expires_in=3600,
            scope="offline read:profile read:sleep read:recovery read:cycles",
        )

    async def get_profile(self, **kwargs: Any) -> dict[str, Any]:
        access_token = str(kwargs["access_token"])
        self.profile_calls.append(access_token)
        if access_token == "stale-access":
            raise WhoopUnauthorizedError("whoop_unauthorized", status_code=401)
        return {"user_id": 42}

    async def get_sleep_collection(self, **kwargs: Any) -> list[dict[str, Any]]:
        assert kwargs["access_token"] == "access-2"
        return []

    async def get_recovery_collection(self, **kwargs: Any) -> list[dict[str, Any]]:
        assert kwargs["access_token"] == "access-2"
        return []

    async def get_cycle_collection(self, **kwargs: Any) -> list[dict[str, Any]]:
        assert kwargs["access_token"] == "access-2"
        return []


class RefreshFailsWhoopClient(UnauthorizedThenSuccessWhoopClient):
    async def refresh_access_token(self, **kwargs: Any) -> object:
        self.refresh_calls += 1
        raise WhoopClientError("whoop_refresh_failed")


class RetryStillUnauthorizedWhoopClient(UnauthorizedThenSuccessWhoopClient):
    async def get_profile(self, **kwargs: Any) -> dict[str, Any]:
        access_token = str(kwargs["access_token"])
        self.profile_calls.append(access_token)
        raise WhoopUnauthorizedError("whoop_unauthorized", status_code=401)


@pytest.mark.asyncio
async def test_whoop_sync_refreshes_rotated_tokens_and_upserts_pending_raw_records() -> None:
    cipher = SecretCipher(SecretCipher.generate_key())
    repository = FakeWhoopRepository(cipher)
    service = WhoopSyncService(
        repository=repository,
        cipher=cipher,
        client=FakeWhoopClient(),
    )

    result = await service.sync_whoop_user("integration-1", now=NOW)
    await service.sync_whoop_user("integration-1", now=NOW)

    assert result.status == "synced"
    assert len(repository.updated_tokens) == 1
    assert cipher.decrypt(repository.integration.access_token_encrypted) == "access-2"
    assert cipher.decrypt(repository.integration.refresh_token_encrypted) == "refresh-2"
    assert repository.profile == {"user_id": 42, "email": "private@example.com"}
    assert {record["score_state"] for record in repository.sleep_records} == {
        "PENDING_SCORE",
        "UNSCORABLE",
    }
    assert len(repository.sleep_records) == 2
    assert repository.recovery_records[0]["score"]["recovery_score"] == 77
    assert repository.cycle_records[0]["score_state"] == "SCORED"
    assert repository.successes == [NOW, NOW]
    assert repository.errors == []


@pytest.mark.asyncio
async def test_whoop_sync_refreshes_once_and_retries_after_401_with_stale_access_token() -> None:
    cipher = SecretCipher(SecretCipher.generate_key())
    repository = FakeWhoopRepository(cipher)
    repository.integration.access_token_encrypted = cipher.encrypt("stale-access")
    repository.integration.refresh_token_encrypted = cipher.encrypt("refresh-1")
    repository.integration.expires_at = NOW + timedelta(hours=1)
    client = UnauthorizedThenSuccessWhoopClient()
    service = WhoopSyncService(repository=repository, cipher=cipher, client=client)

    result = await service.sync_whoop_user("integration-1", now=NOW)

    assert result.status == "synced"
    assert client.refresh_calls == 1
    assert client.profile_calls == ["stale-access", "access-2"]
    assert cipher.decrypt(repository.integration.access_token_encrypted) == "access-2"
    assert cipher.decrypt(repository.integration.refresh_token_encrypted) == "refresh-2"
    assert repository.successes == [NOW]
    assert repository.errors == []


@pytest.mark.asyncio
async def test_whoop_sync_refresh_failure_after_401_is_controlled_without_token_leak() -> None:
    cipher = SecretCipher(SecretCipher.generate_key())
    repository = FakeWhoopRepository(cipher)
    repository.integration.access_token_encrypted = cipher.encrypt("stale-access")
    repository.integration.refresh_token_encrypted = cipher.encrypt("refresh-1")
    repository.integration.expires_at = NOW + timedelta(hours=1)
    client = RefreshFailsWhoopClient()
    service = WhoopSyncService(repository=repository, cipher=cipher, client=client)

    result = await service.sync_whoop_user("integration-1", now=NOW)

    assert result.status == "failed"
    assert result.error_code == "whoop_refresh_failed"
    assert client.refresh_calls == 1
    assert repository.errors == ["whoop_refresh_failed"]
    assert "refresh-1" not in repository.errors[0]


@pytest.mark.asyncio
async def test_whoop_sync_retries_401_only_once_without_loop() -> None:
    cipher = SecretCipher(SecretCipher.generate_key())
    repository = FakeWhoopRepository(cipher)
    repository.integration.access_token_encrypted = cipher.encrypt("stale-access")
    repository.integration.refresh_token_encrypted = cipher.encrypt("refresh-1")
    repository.integration.expires_at = NOW + timedelta(hours=1)
    client = RetryStillUnauthorizedWhoopClient()
    service = WhoopSyncService(repository=repository, cipher=cipher, client=client)

    result = await service.sync_whoop_user("integration-1", now=NOW)

    assert result.status == "failed"
    assert result.error_code == "whoop_unauthorized"
    assert client.refresh_calls == 1
    assert client.profile_calls == ["stale-access", "access-2"]
    assert len(repository.updated_tokens) == 1
    assert repository.errors == ["whoop_unauthorized"]


def test_whoop_worker_is_registered() -> None:
    assert jobs.sync_whoop_integrations in WorkerSettings.functions
    assert any(
        getattr(cron_job, "coroutine", None) is jobs.sync_whoop_integrations
        or getattr(cron_job, "name", "") == "cron:sync_whoop_integrations"
        for cron_job in WorkerSettings.cron_jobs
    )


class FakeWorkerSessionContext:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


class FakeWorkerSessionLocal:
    def __call__(self) -> FakeWorkerSessionContext:
        return FakeWorkerSessionContext()


class FakeWorkerWhoopRepository:
    integrations: list[object] = []
    instances: list[FakeWorkerWhoopRepository] = []

    def __init__(self, session: object) -> None:
        del session
        self.__class__.instances.append(self)

    async def list_connected(self) -> list[object]:
        return list(self.__class__.integrations)

    async def get_connected_for_update(self, integration_id: str) -> object | None:
        for integration in self.__class__.integrations:
            if str(getattr(integration, "id", "")) == integration_id:
                return integration
        return None


class FakeWorkerWhoopSyncService:
    calls: list[str] = []

    def __init__(self, **kwargs: object) -> None:
        del kwargs

    async def sync_whoop_user(self, integration_id: str, *, now: object) -> object:
        del now
        self.__class__.calls.append(integration_id)
        return SimpleNamespace(status="synced", error_code=None)


@pytest.mark.asyncio
async def test_whoop_worker_skips_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeWorkerWhoopRepository.instances = []
    FakeWorkerWhoopSyncService.calls = []
    monkeypatch.setattr(jobs, "get_settings", lambda: Settings(whoop_enabled=False))
    monkeypatch.setattr(jobs, "SessionLocal", FakeWorkerSessionLocal())
    monkeypatch.setattr(jobs, "WhoopIntegrationRepository", FakeWorkerWhoopRepository)
    monkeypatch.setattr(jobs, "WhoopSyncService", FakeWorkerWhoopSyncService)

    await jobs.sync_whoop_integrations({"redis": FakeRedis()})

    assert FakeWorkerWhoopRepository.instances == []
    assert FakeWorkerWhoopSyncService.calls == []


@pytest.mark.asyncio
async def test_whoop_worker_skips_when_no_connected_integrations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeWorkerWhoopRepository.integrations = []
    FakeWorkerWhoopSyncService.calls = []
    monkeypatch.setattr(
        jobs,
        "get_settings",
        lambda: Settings(
            whoop_enabled=True,
            whoop_client_id="client-id",
            whoop_client_secret="client-secret",
            whoop_redirect_uri="https://jarvis.example.com/integrations/whoop/oauth/callback",
            whoop_token_encryption_key=SecretCipher.generate_key(),
        ),
    )
    monkeypatch.setattr(jobs, "SessionLocal", FakeWorkerSessionLocal())
    monkeypatch.setattr(jobs, "WhoopIntegrationRepository", FakeWorkerWhoopRepository)
    monkeypatch.setattr(jobs, "WhoopSyncService", FakeWorkerWhoopSyncService)

    await jobs.sync_whoop_integrations({"redis": FakeRedis()})

    assert FakeWorkerWhoopSyncService.calls == []


@pytest.mark.asyncio
async def test_whoop_worker_redis_lock_prevents_concurrent_sync(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = FakeRedis()
    redis.values["whoop:sync:integration-1"] = "1"
    FakeWorkerWhoopRepository.integrations = [SimpleNamespace(id="integration-1")]
    FakeWorkerWhoopSyncService.calls = []
    monkeypatch.setattr(
        jobs,
        "get_settings",
        lambda: Settings(
            whoop_enabled=True,
            whoop_client_id="client-id",
            whoop_client_secret="client-secret",
            whoop_redirect_uri="https://jarvis.example.com/integrations/whoop/oauth/callback",
            whoop_token_encryption_key=SecretCipher.generate_key(),
        ),
    )
    monkeypatch.setattr(jobs, "SessionLocal", FakeWorkerSessionLocal())
    monkeypatch.setattr(jobs, "WhoopIntegrationRepository", FakeWorkerWhoopRepository)
    monkeypatch.setattr(jobs, "WhoopSyncService", FakeWorkerWhoopSyncService)

    await jobs.sync_whoop_integrations({"redis": redis})

    assert FakeWorkerWhoopSyncService.calls == []
