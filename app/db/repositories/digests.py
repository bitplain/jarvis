from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import select

from app.db.models import DigestPolicy, utcnow
from app.services.digests import (
    DigestPolicyInput,
    StoredDigestPolicy,
    _default_policy_inputs,
    _is_policy_due,
    _scope_filter,
    _timezone,
    _validate_send_time,
)


class DigestPolicyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def ensure_default_policies(self) -> list[StoredDigestPolicy]:
        existing = {
            policy.key: policy
            for policy in (
                await self.session.execute(select(DigestPolicy))
            ).scalars().all()
        }
        changed = False
        for policy_input in _default_policy_inputs():
            if policy_input.key in existing:
                continue
            self.session.add(_model_from_input(policy_input))
            changed = True
        if changed:
            await self.session.commit()
        return await self.list_policies()

    async def list_policies(self) -> list[StoredDigestPolicy]:
        result = await self.session.execute(select(DigestPolicy).order_by(DigestPolicy.key))
        policies = [_to_stored(policy) for policy in result.scalars().all()]
        order = {"personal_morning": 0, "work_start": 1}
        return sorted(policies, key=lambda policy: order.get(policy.key, 99))

    async def get_by_key(self, key: str) -> StoredDigestPolicy | None:
        result = await self.session.execute(
            select(DigestPolicy).where(DigestPolicy.key == key.strip().lower()).limit(1)
        )
        policy = result.scalar_one_or_none()
        return _to_stored(policy) if policy is not None else None

    async def update_enabled(self, key: str, enabled: bool) -> StoredDigestPolicy | None:
        policy = await self._get_model(key)
        if policy is None:
            return None
        policy.enabled = enabled
        policy.updated_at = utcnow()
        await self.session.commit()
        await self.session.refresh(policy)
        return _to_stored(policy)

    async def update_schedule(
        self,
        key: str,
        *,
        send_time: str | None,
        timezone: str | None,
    ) -> StoredDigestPolicy | None:
        policy = await self._get_model(key)
        if policy is None:
            return None
        if send_time is not None:
            _validate_send_time(send_time)
            policy.send_time = send_time
        if timezone is not None:
            _timezone(timezone)
            policy.timezone = timezone
        policy.updated_at = utcnow()
        await self.session.commit()
        await self.session.refresh(policy)
        return _to_stored(policy)

    async def set_target_chat_id(
        self,
        key: str,
        target_chat_id: int,
    ) -> StoredDigestPolicy | None:
        policy = await self._get_model(key)
        if policy is None:
            return None
        policy.target_chat_id = target_chat_id
        policy.updated_at = utcnow()
        await self.session.commit()
        await self.session.refresh(policy)
        return _to_stored(policy)

    async def due_for_delivery(self, now: datetime) -> list[StoredDigestPolicy]:
        await self.ensure_default_policies()
        result = await self.session.execute(
            select(DigestPolicy)
            .where(DigestPolicy.enabled.is_(True))
            .order_by(DigestPolicy.updated_at)
        )
        return [
            _to_stored(policy)
            for policy in result.scalars().all()
            if _is_policy_due(_to_stored(policy), now, grace_minutes=30)
        ]

    async def mark_sent_if_due(
        self,
        key: str,
        local_date: date,
        *,
        sent_at: datetime,
    ) -> bool:
        result = await self.session.execute(
            update(DigestPolicy)
            .where(
                DigestPolicy.key == key.strip().lower(),
                DigestPolicy.last_sent_date.is_distinct_from(local_date),
            )
            .values(last_sent_date=local_date, last_sent_at=sent_at, updated_at=utcnow())
        )
        await self.session.commit()
        return bool(getattr(result, "rowcount", 0))

    async def _get_model(self, key: str) -> DigestPolicy | None:
        result = await self.session.execute(
            select(DigestPolicy).where(DigestPolicy.key == key.strip().lower()).limit(1)
        )
        return result.scalar_one_or_none()


def _model_from_input(policy: DigestPolicyInput) -> DigestPolicy:
    _validate_send_time(policy.send_time)
    _timezone(policy.timezone)
    scopes = _scope_filter(policy.scope_filter_json)
    now = utcnow()
    return DigestPolicy(
        key=policy.key,
        title=policy.title,
        enabled=policy.enabled,
        scope_filter_json={"scopes": scopes},
        send_time=policy.send_time,
        timezone=policy.timezone,
        target_chat_id=policy.target_chat_id,
        last_sent_date=policy.last_sent_date,
        last_sent_at=policy.last_sent_at,
        created_at=now,
        updated_at=now,
    )


def _to_stored(policy: DigestPolicy) -> StoredDigestPolicy:
    return StoredDigestPolicy(
        id=policy.id.hex if isinstance(policy.id, UUID) else str(policy.id),
        key=policy.key,
        title=policy.title,
        enabled=policy.enabled,
        scope_filter_json={"scopes": _scope_filter(policy.scope_filter_json or {})},
        send_time=policy.send_time,
        timezone=policy.timezone,
        target_chat_id=policy.target_chat_id,
        last_sent_date=policy.last_sent_date,
        last_sent_at=policy.last_sent_at,
        created_at=policy.created_at,
        updated_at=policy.updated_at,
    )
