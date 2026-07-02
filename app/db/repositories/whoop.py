from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    WhoopCycleRecord,
    WhoopIntegration,
    WhoopIntegrationStatus,
    WhoopRecoveryRecord,
    WhoopSleepRecord,
    utcnow,
)


class WhoopIntegrationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_connected_for_update(self, integration_id: str) -> WhoopIntegration | None:
        result = await self.session.execute(
            select(WhoopIntegration)
            .where(
                WhoopIntegration.id == _uuid(integration_id),
                WhoopIntegration.status.in_(
                    [
                        WhoopIntegrationStatus.CONNECTED.value,
                        WhoopIntegrationStatus.ERROR.value,
                    ]
                ),
            )
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_by_telegram_user_id(self, telegram_user_id: int) -> WhoopIntegration | None:
        result = await self.session.execute(
            select(WhoopIntegration)
            .where(WhoopIntegration.telegram_user_id == telegram_user_id)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_connected(self) -> list[WhoopIntegration]:
        result = await self.session.execute(
            select(WhoopIntegration)
            .where(
                WhoopIntegration.status.in_(
                    [
                        WhoopIntegrationStatus.CONNECTED.value,
                        WhoopIntegrationStatus.ERROR.value,
                    ]
                )
            )
            .order_by(WhoopIntegration.updated_at)
        )
        return list(result.scalars().all())

    async def upsert_connected_integration(
        self,
        *,
        telegram_user_id: int,
        scope: str,
        access_token_encrypted: str,
        refresh_token_encrypted: str,
        expires_at: datetime,
        whoop_user_id: int | None,
        profile_json: dict[str, Any],
    ) -> WhoopIntegration:
        now = utcnow()
        integration = await self.get_by_telegram_user_id(telegram_user_id)
        if integration is None:
            integration = WhoopIntegration(
                user_id=telegram_user_id,
                telegram_user_id=telegram_user_id,
                status=WhoopIntegrationStatus.CONNECTED.value,
                scope=scope,
                access_token_encrypted=access_token_encrypted,
                refresh_token_encrypted=refresh_token_encrypted,
                expires_at=expires_at,
                whoop_user_id=whoop_user_id,
                profile_json=profile_json,
                created_at=now,
                updated_at=now,
            )
            self.session.add(integration)
        else:
            integration.status = WhoopIntegrationStatus.CONNECTED.value
            integration.scope = scope
            integration.access_token_encrypted = access_token_encrypted
            integration.refresh_token_encrypted = refresh_token_encrypted
            integration.expires_at = expires_at
            integration.whoop_user_id = whoop_user_id
            integration.profile_json = profile_json
            integration.last_error = None
            integration.updated_at = now
        await self.session.commit()
        await self.session.refresh(integration)
        return integration

    async def revoke_for_telegram_user_id(self, telegram_user_id: int) -> WhoopIntegration | None:
        integration = await self.get_by_telegram_user_id(telegram_user_id)
        if integration is None:
            return None
        integration.status = WhoopIntegrationStatus.REVOKED.value
        integration.access_token_encrypted = None
        integration.refresh_token_encrypted = None
        integration.expires_at = None
        integration.updated_at = utcnow()
        await self.session.commit()
        await self.session.refresh(integration)
        return integration

    async def update_tokens(
        self,
        integration_id: str,
        *,
        access_token_encrypted: str,
        refresh_token_encrypted: str,
        expires_at: datetime,
        scope: str,
    ) -> None:
        integration = await self._get_model(integration_id)
        if integration is None:
            return
        integration.access_token_encrypted = access_token_encrypted
        integration.refresh_token_encrypted = refresh_token_encrypted
        integration.expires_at = expires_at
        integration.scope = scope
        integration.updated_at = utcnow()
        await self.session.commit()

    async def update_profile(
        self,
        integration_id: str,
        *,
        whoop_user_id: int | None,
        profile_json: dict[str, Any],
    ) -> None:
        integration = await self._get_model(integration_id)
        if integration is None:
            return
        integration.whoop_user_id = whoop_user_id
        integration.profile_json = profile_json
        integration.updated_at = utcnow()
        await self.session.commit()

    async def mark_sync_success(self, integration_id: str, *, synced_at: datetime) -> None:
        integration = await self._get_model(integration_id)
        if integration is None:
            return
        integration.status = WhoopIntegrationStatus.CONNECTED.value
        integration.last_sync_at = synced_at
        integration.last_error = None
        integration.updated_at = utcnow()
        await self.session.commit()

    async def mark_sync_error(self, integration_id: str, *, error_code: str) -> None:
        integration = await self._get_model(integration_id)
        if integration is None:
            return
        integration.status = WhoopIntegrationStatus.ERROR.value
        integration.last_error = error_code
        integration.updated_at = utcnow()
        await self.session.commit()

    async def upsert_sleep_record(self, integration_id: str, record: dict[str, Any]) -> None:
        integration = await self._get_model(integration_id)
        if integration is None:
            return
        sleep_id = str(record["id"])
        result = await self.session.execute(
            select(WhoopSleepRecord).where(
                WhoopSleepRecord.integration_id == integration.id,
                WhoopSleepRecord.whoop_sleep_id == sleep_id,
            )
        )
        sleep = result.scalar_one_or_none()
        values = {
            "user_id": integration.user_id,
            "whoop_sleep_id": sleep_id,
            "cycle_id": _required_int("cycle_id", record["cycle_id"]),
            "start_at": _parse_datetime(record["start"]),
            "end_at": _parse_datetime(record["end"]),
            "timezone_offset": str(record.get("timezone_offset") or ""),
            "nap": bool(record.get("nap", False)),
            "score_state": str(record.get("score_state") or ""),
            "raw_json": record,
            "updated_at": utcnow(),
        }
        if sleep is None:
            sleep = WhoopSleepRecord(integration_id=integration.id, created_at=utcnow(), **values)
            self.session.add(sleep)
        else:
            for key, value in values.items():
                setattr(sleep, key, value)
        await self.session.commit()

    async def upsert_recovery_record(self, integration_id: str, record: dict[str, Any]) -> None:
        integration = await self._get_model(integration_id)
        if integration is None:
            return
        cycle_id = _required_int("cycle_id", record["cycle_id"])
        result = await self.session.execute(
            select(WhoopRecoveryRecord).where(
                WhoopRecoveryRecord.integration_id == integration.id,
                WhoopRecoveryRecord.cycle_id == cycle_id,
            )
        )
        recovery = result.scalar_one_or_none()
        raw_score = record.get("score")
        score: dict[str, Any] = raw_score if isinstance(raw_score, dict) else {}
        values = {
            "user_id": integration.user_id,
            "cycle_id": cycle_id,
            "score_state": record.get("score_state"),
            "recovery_score": _optional_int(score.get("recovery_score")),
            "hrv_rmssd_milli": _optional_decimal(score.get("hrv_rmssd_milli")),
            "resting_heart_rate": _optional_int(score.get("resting_heart_rate")),
            "raw_json": record,
            "updated_at": utcnow(),
        }
        if recovery is None:
            recovery = WhoopRecoveryRecord(
                integration_id=integration.id,
                created_at=utcnow(),
                **values,
            )
            self.session.add(recovery)
        else:
            for key, value in values.items():
                setattr(recovery, key, value)
        await self.session.commit()

    async def upsert_cycle_record(self, integration_id: str, record: dict[str, Any]) -> None:
        integration = await self._get_model(integration_id)
        if integration is None:
            return
        cycle_id = _required_int("cycle_id", record.get("id") or record["cycle_id"])
        result = await self.session.execute(
            select(WhoopCycleRecord).where(
                WhoopCycleRecord.integration_id == integration.id,
                WhoopCycleRecord.cycle_id == cycle_id,
            )
        )
        cycle = result.scalar_one_or_none()
        end = record.get("end")
        values = {
            "user_id": integration.user_id,
            "cycle_id": cycle_id,
            "start_at": _parse_datetime(record["start"]),
            "end_at": _parse_datetime(end) if end else None,
            "timezone_offset": str(record.get("timezone_offset") or ""),
            "score_state": str(record.get("score_state") or ""),
            "raw_json": record,
            "updated_at": utcnow(),
        }
        if cycle is None:
            cycle = WhoopCycleRecord(integration_id=integration.id, created_at=utcnow(), **values)
            self.session.add(cycle)
        else:
            for key, value in values.items():
                setattr(cycle, key, value)
        await self.session.commit()

    async def list_recent_sleep_records(
        self,
        integration_id: str,
        *,
        since: datetime,
        limit: int,
    ) -> list[WhoopSleepRecord]:
        result = await self.session.execute(
            select(WhoopSleepRecord)
            .where(
                WhoopSleepRecord.integration_id == _uuid(integration_id),
                WhoopSleepRecord.start_at >= since,
            )
            .order_by(WhoopSleepRecord.start_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_recovery_by_cycle_id(
        self,
        integration_id: str,
        *,
        cycle_id: int,
    ) -> WhoopRecoveryRecord | None:
        result = await self.session.execute(
            select(WhoopRecoveryRecord)
            .where(
                WhoopRecoveryRecord.integration_id == _uuid(integration_id),
                WhoopRecoveryRecord.cycle_id == cycle_id,
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def status_snapshot(self) -> dict[str, Any]:
        connected = await self.session.execute(
            select(func.count(WhoopIntegration.id)).where(
                WhoopIntegration.status == WhoopIntegrationStatus.CONNECTED.value
            )
        )
        last_sync = await self.session.execute(select(func.max(WhoopIntegration.last_sync_at)))
        last_error_count = await self.session.execute(
            select(func.count(WhoopIntegration.id)).where(WhoopIntegration.last_error.is_not(None))
        )
        return {
            "connected_integrations": int(connected.scalar_one()),
            "last_sync": last_sync.scalar_one(),
            "last_error_count": int(last_error_count.scalar_one()),
        }

    async def _get_model(self, integration_id: str) -> WhoopIntegration | None:
        result = await self.session.execute(
            select(WhoopIntegration).where(WhoopIntegration.id == _uuid(integration_id)).limit(1)
        )
        return result.scalar_one_or_none()


def _uuid(value: str | UUID) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


def _parse_datetime(value: object) -> datetime:
    text = str(value)
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _required_int(field_name: str, value: object) -> int:
    parsed = _optional_int(value)
    if parsed is None:
        raise ValueError(f"{field_name}_invalid")
    return parsed


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        try:
            numeric = Decimal(text)
        except (InvalidOperation, ValueError):
            return None
        if not numeric.is_finite() or numeric != numeric.to_integral_value():
            return None
        return int(numeric)


def _optional_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        numeric = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    if not numeric.is_finite():
        return None
    return numeric
