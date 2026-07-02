from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.repositories.whoop import WhoopIntegrationRepository
from app.db.session import SessionLocal
from app.services.secret_cipher import SecretCipher
from app.services.whoop_client import (
    WhoopClient,
    WhoopClientError,
    WhoopTokenSet,
    WhoopUnauthorizedError,
)

SAFE_SCORE_STATES = {"SCORED", "PENDING_SCORE", "UNSCORABLE"}
TOKEN_REFRESH_SKEW_SECONDS = 300


@dataclass(frozen=True)
class WhoopSyncResult:
    status: str
    sleep_records: int = 0
    recovery_records: int = 0
    cycle_records: int = 0
    error_code: str | None = None


@dataclass(frozen=True)
class WhoopFetchedData:
    profile: dict[str, Any]
    sleep_records: list[dict[str, Any]]
    recovery_records: list[dict[str, Any]]
    cycle_records: list[dict[str, Any]]


class WhoopSyncService:
    def __init__(
        self,
        *,
        repository: Any,
        cipher: SecretCipher,
        client: Any,
    ) -> None:
        self.repository = repository
        self.cipher = cipher
        self.client = client

    async def sync_whoop_user(
        self,
        integration_id: str,
        *,
        now: datetime | None = None,
        lookback_hours: int = 48,
    ) -> WhoopSyncResult:
        resolved_now = now or datetime.now(UTC)
        integration = await self.repository.get_connected_for_update(integration_id)
        if integration is None:
            return WhoopSyncResult(status="skipped")
        try:
            access_token = self.cipher.decrypt(str(integration.access_token_encrypted or ""))
            refresh_token = self.cipher.decrypt(str(integration.refresh_token_encrypted or ""))
            expires_at = _aware_utc(getattr(integration, "expires_at", None))
            if expires_at is None or expires_at <= resolved_now + timedelta(
                seconds=TOKEN_REFRESH_SKEW_SECONDS
            ):
                token_set = await self._refresh_and_store_tokens(
                    integration_id,
                    refresh_token=refresh_token,
                    now=resolved_now,
                )
                access_token = token_set.access_token
                refresh_token = token_set.refresh_token
            start = resolved_now - timedelta(hours=lookback_hours)
            try:
                fetched = await self._fetch_recent_data(
                    access_token=access_token,
                    start=start,
                    end=resolved_now,
                )
            except WhoopUnauthorizedError:
                token_set = await self._refresh_and_store_tokens(
                    integration_id,
                    refresh_token=refresh_token,
                    now=resolved_now,
                )
                access_token = token_set.access_token
                fetched = await self._fetch_recent_data(
                    access_token=access_token,
                    start=start,
                    end=resolved_now,
                )
            await self.repository.update_profile(
                integration_id,
                whoop_user_id=_optional_int(fetched.profile.get("user_id")),
                profile_json=fetched.profile,
            )
            for record in fetched.sleep_records:
                _validate_score_state(record)
                await self.repository.upsert_sleep_record(integration_id, record)
            for record in fetched.recovery_records:
                _validate_score_state(record)
                await self.repository.upsert_recovery_record(integration_id, record)
            for record in fetched.cycle_records:
                _validate_score_state(record)
                await self.repository.upsert_cycle_record(integration_id, record)
            await self.repository.mark_sync_success(integration_id, synced_at=resolved_now)
        except WhoopClientError as exc:
            await self.repository.mark_sync_error(integration_id, error_code=exc.code)
            return WhoopSyncResult(status="failed", error_code=exc.code)
        except Exception as exc:
            error_code = f"whoop_sync_{type(exc).__name__}"
            await self.repository.mark_sync_error(integration_id, error_code=error_code)
            return WhoopSyncResult(status="failed", error_code=error_code)
        return WhoopSyncResult(
            status="synced",
            sleep_records=len(fetched.sleep_records),
            recovery_records=len(fetched.recovery_records),
            cycle_records=len(fetched.cycle_records),
        )

    async def _refresh_and_store_tokens(
        self,
        integration_id: str,
        *,
        refresh_token: str,
        now: datetime,
    ) -> WhoopTokenSet:
        token_set = cast(
            WhoopTokenSet,
            await self.client.refresh_access_token(refresh_token=refresh_token),
        )
        await self.repository.update_tokens(
            integration_id,
            access_token_encrypted=self.cipher.encrypt(token_set.access_token),
            refresh_token_encrypted=self.cipher.encrypt(token_set.refresh_token),
            expires_at=now + timedelta(seconds=token_set.expires_in),
            scope=token_set.scope,
        )
        return token_set

    async def _fetch_recent_data(
        self,
        *,
        access_token: str,
        start: datetime,
        end: datetime,
    ) -> WhoopFetchedData:
        profile = await self.client.get_profile(access_token=access_token)
        sleep_records = await self.client.get_sleep_collection(
            access_token=access_token,
            start=start,
            end=end,
        )
        recovery_records = await self.client.get_recovery_collection(
            access_token=access_token,
            start=start,
            end=end,
        )
        cycle_records = await self.client.get_cycle_collection(
            access_token=access_token,
            start=start,
            end=end,
        )
        return WhoopFetchedData(
            profile=profile,
            sleep_records=sleep_records,
            recovery_records=recovery_records,
            cycle_records=cycle_records,
        )


async def sync_whoop_user(
    integration_id: str,
    now: datetime | None = None,
    *,
    session: AsyncSession | None = None,
    settings: Settings | None = None,
) -> WhoopSyncResult:
    resolved_settings = settings or get_settings()
    cipher = SecretCipher(resolved_settings.whoop_token_encryption_key)
    client = WhoopClient(resolved_settings)
    if session is not None:
        service = WhoopSyncService(
            repository=WhoopIntegrationRepository(session),
            cipher=cipher,
            client=client,
        )
        return await service.sync_whoop_user(integration_id, now=now)
    async with SessionLocal() as created_session:
        service = WhoopSyncService(
            repository=WhoopIntegrationRepository(created_session),
            cipher=cipher,
            client=client,
        )
        return await service.sync_whoop_user(integration_id, now=now)


async def sync_recent_whoop_data(
    integration_id: str,
    *,
    lookback_hours: int = 48,
    now: datetime | None = None,
    session: AsyncSession | None = None,
    settings: Settings | None = None,
) -> WhoopSyncResult:
    resolved_settings = settings or get_settings()
    cipher = SecretCipher(resolved_settings.whoop_token_encryption_key)
    client = WhoopClient(resolved_settings)
    if session is not None:
        service = WhoopSyncService(
            repository=WhoopIntegrationRepository(session),
            cipher=cipher,
            client=client,
        )
        return await service.sync_whoop_user(
            integration_id,
            now=now,
            lookback_hours=lookback_hours,
        )
    async with SessionLocal() as created_session:
        service = WhoopSyncService(
            repository=WhoopIntegrationRepository(created_session),
            cipher=cipher,
            client=client,
        )
        return await service.sync_whoop_user(
            integration_id,
            now=now,
            lookback_hours=lookback_hours,
        )


def expires_at_from_token(token_set: WhoopTokenSet, *, now: datetime | None = None) -> datetime:
    return (now or datetime.now(UTC)) + timedelta(seconds=token_set.expires_in)


def _validate_score_state(record: dict[str, Any]) -> None:
    state = record.get("score_state")
    if state is not None and str(state) not in SAFE_SCORE_STATES:
        record["score_state"] = str(state)


def _aware_utc(value: object) -> datetime | None:
    if value is None or not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return int(str(value))
