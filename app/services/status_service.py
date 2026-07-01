from __future__ import annotations

from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import (
    DigestPolicy,
    HelpdeskEmailEvent,
    HelpdeskImapMailboxState,
    HelpdeskVacationState,
    Reminder,
    RuntimeSetting,
    TelegramAccessEntry,
)
from app.db.repositories.runtime_settings import RuntimeSettingRepository
from app.services.helpdesk_imap.config import HelpdeskImapConfig
from app.services.helpdesk_imap.service import (
    HELPDESK_LAST_CHECK_KEY,
    HELPDESK_LAST_ERROR_KEY,
    HELPDESK_LAST_SUCCESS_KEY,
)
from app.services.helpdesk_vacation import HELPDESK_VACATION_NOTIFY_STATUS
from app.services.runtime_settings_service import ActiveLLMProvider, RuntimeSettingsService

WORKER_HEARTBEAT_KEY = "jarvis:worker:heartbeat"
WORKER_HEARTBEAT_TTL_SECONDS = 600
WORKER_HEARTBEAT_FRESH_SECONDS = 300


def is_worker_heartbeat_fresh(
    heartbeat_at: datetime | None,
    *,
    now: datetime | None = None,
) -> bool:
    if heartbeat_at is None:
        return False
    resolved_now = now or datetime.now(UTC)
    if heartbeat_at.tzinfo is None:
        heartbeat_at = heartbeat_at.replace(tzinfo=UTC)
    return (resolved_now - heartbeat_at).total_seconds() <= WORKER_HEARTBEAT_FRESH_SECONDS


async def record_worker_heartbeat(redis: Any) -> None:
    if redis is None:
        return
    try:
        await redis.set(
            WORKER_HEARTBEAT_KEY,
            datetime.now(UTC).isoformat(),
            ex=WORKER_HEARTBEAT_TTL_SECONDS,
        )
    except Exception:
        return


class StatusService:
    def __init__(self, settings: Settings, *, session: AsyncSession | None, redis: Any) -> None:
        self.settings = settings
        self.session = session
        self.redis = redis

    async def collect(self) -> dict[str, Any]:
        postgres = await self._check_postgres()
        redis = await self._check_redis()
        return {
            "api": {"ok": True},
            "postgres": postgres,
            "redis": redis,
            "worker": await self._check_worker(),
            "webhook": self._check_webhook(),
            "reminders": await self._check_reminders(postgres["ok"]),
            "provider": await self._provider(),
            "draft_streaming": {"ok": self._draft_streaming_enabled()},
            "prompt_profiles": await self._prompt_profiles(postgres["ok"]),
            "access_db": await self._access_db(postgres["ok"]),
            "digests": await self._digests(postgres["ok"]),
            "helpdesk_imap": await self._helpdesk_imap(postgres["ok"]),
        }

    async def _check_postgres(self) -> dict[str, Any]:
        if self.session is None:
            return {"ok": False, "latency_ms": None}
        started = perf_counter()
        try:
            await self.session.execute(text("SELECT 1"))
        except Exception:
            await self.session.rollback()
            return {"ok": False, "latency_ms": None}
        return {"ok": True, "latency_ms": _elapsed_ms(started)}

    async def _check_redis(self) -> dict[str, Any]:
        if self.redis is None:
            return {"ok": False, "latency_ms": None}
        started = perf_counter()
        try:
            ok = bool(await self.redis.ping())
        except Exception:
            return {"ok": False, "latency_ms": None}
        return {"ok": ok, "latency_ms": _elapsed_ms(started) if ok else None}

    async def _check_worker(self) -> dict[str, Any]:
        if self.redis is None:
            return {"ok": False, "age_seconds": None}
        try:
            raw = await self.redis.get(WORKER_HEARTBEAT_KEY)
        except Exception:
            return {"ok": False, "age_seconds": None}
        heartbeat_at = _parse_heartbeat(raw)
        now = datetime.now(UTC)
        age = None
        if heartbeat_at is not None:
            age = int((now - heartbeat_at).total_seconds())
        return {"ok": is_worker_heartbeat_fresh(heartbeat_at, now=now), "age_seconds": age}

    def _check_webhook(self) -> dict[str, str]:
        if (
            self.settings.telegram_bot_token
            and self.settings.telegram_webhook_secret
            and self.settings.public_base_url
        ):
            return {"state": "configured"}
        return {"state": "unknown"}

    async def _check_reminders(self, postgres_ok: bool) -> dict[str, Any]:
        if self.session is None or not postgres_ok:
            return {"ok": False, "due_count": None}
        try:
            result = await self.session.execute(
                select(func.count(Reminder.id)).where(
                    Reminder.status == "scheduled",
                    Reminder.remind_at <= datetime.now(UTC),
                )
            )
        except Exception:
            await self.session.rollback()
            return {"ok": False, "due_count": None}
        return {"ok": True, "due_count": int(result.scalar_one())}

    async def _provider(self) -> dict[str, str]:
        if self.session is None:
            return {"label": "Auto"}
        try:
            provider = await RuntimeSettingsService(
                RuntimeSettingRepository(self.session)
            ).get_active_llm_provider()
        except Exception:
            provider = ActiveLLMProvider.AUTO
        labels = {
            ActiveLLMProvider.AUTO: "Auto",
            ActiveLLMProvider.YANDEX: "Yandex",
            ActiveLLMProvider.OPENROUTER: "OpenRouter",
        }
        return {"label": labels[provider]}

    def _draft_streaming_enabled(self) -> bool:
        return (
            self.settings.streaming_enabled
            and self.settings.streaming_private_draft_enabled
            and self.settings.telegram_private_draft_streaming_enabled
        )

    async def _prompt_profiles(self, postgres_ok: bool) -> dict[str, bool]:
        if self.session is None or not postgres_ok:
            return {"ok": False}
        try:
            await self.session.execute(select(RuntimeSetting.key).limit(1))
        except Exception:
            await self.session.rollback()
            return {"ok": False}
        return {"ok": True}

    async def _access_db(self, postgres_ok: bool) -> dict[str, bool]:
        if self.session is None or not postgres_ok:
            return {"ok": False}
        try:
            await self.session.execute(select(TelegramAccessEntry.id).limit(1))
        except Exception:
            await self.session.rollback()
            return {"ok": False}
        return {"ok": True}

    async def _digests(self, postgres_ok: bool) -> dict[str, Any]:
        if self.session is None or not postgres_ok:
            return {"ok": False, "policies": []}
        try:
            result = await self.session.execute(select(DigestPolicy).order_by(DigestPolicy.key))
            order = {"personal_morning": 0, "work_start": 1}
            policies = sorted(result.scalars().all(), key=lambda policy: order.get(policy.key, 99))
        except Exception:
            await self.session.rollback()
            return {"ok": False, "policies": []}
        return {
            "ok": True,
            "policies": [
                {
                    "key": policy.key,
                    "enabled": bool(policy.enabled),
                    "send_time": policy.send_time,
                    "timezone": policy.timezone,
                    "chat": "configured" if policy.target_chat_id is not None else "missing",
                    "last_sent": _iso_or_never(policy.last_sent_at),
                }
                for policy in policies
            ],
        }

    async def _helpdesk_imap(self, postgres_ok: bool) -> dict[str, Any]:
        config = HelpdeskImapConfig.from_settings(self.settings)
        processed_last_24h: int | None = None
        pending_notifications: int | None = None
        failed_notifications: int | None = None
        vacation_enabled = False
        vacation_since = "unknown"
        vacation_last_reviewed = "unknown"
        vacation_new_since_start: int | None = None
        vacation_new_since_last_review: int | None = None
        baseline = "not set"
        last_seen_uid: int | None = None
        mailbox_last_check = "unknown"
        mailbox_last_success = "unknown"
        mailbox_last_error = "none"
        if self.session is not None and postgres_ok:
            try:
                result = await self.session.execute(
                    select(func.count(HelpdeskEmailEvent.id)).where(
                        HelpdeskEmailEvent.created_at >= datetime.now(UTC) - timedelta(hours=24)
                    )
                )
                processed_last_24h = int(result.scalar_one())
                result = await self.session.execute(
                    select(func.count(HelpdeskEmailEvent.id)).where(
                        HelpdeskEmailEvent.notify_status == "pending"
                    )
                )
                pending_notifications = int(result.scalar_one())
                result = await self.session.execute(
                    select(func.count(HelpdeskEmailEvent.id)).where(
                        HelpdeskEmailEvent.notify_status == "failed"
                    )
                )
                failed_notifications = int(result.scalar_one())
                result = await self.session.execute(
                    select(
                        HelpdeskImapMailboxState.folder,
                        HelpdeskImapMailboxState.last_seen_uid,
                        HelpdeskImapMailboxState.baseline_at,
                        HelpdeskImapMailboxState.last_check_at,
                        HelpdeskImapMailboxState.last_success_at,
                        HelpdeskImapMailboxState.last_error_code,
                    ).where(HelpdeskImapMailboxState.folder == config.folder)
                )
                state_row = result.one_or_none()
                if state_row is not None:
                    baseline = "set" if state_row[2] is not None else "not set"
                    last_seen_uid = state_row[1]
                    mailbox_last_check = _iso_or_unknown(state_row[3])
                    mailbox_last_success = _iso_or_unknown(state_row[4])
                    mailbox_last_error = state_row[5] or "none"
            except Exception:
                await self.session.rollback()
                processed_last_24h = None
                pending_notifications = None
                failed_notifications = None
            try:
                vacation_result = await self.session.execute(
                    select(
                        HelpdeskVacationState.enabled,
                        HelpdeskVacationState.enabled_at,
                        HelpdeskVacationState.disabled_at,
                        HelpdeskVacationState.last_reviewed_at,
                    ).where(HelpdeskVacationState.scope == "default")
                )
                vacation_row = vacation_result.one_or_none()
                if vacation_row is not None:
                    vacation_enabled = bool(vacation_row[0])
                    vacation_since = _iso_or_unknown(vacation_row[1])
                    vacation_last_reviewed = _iso_or_unknown(vacation_row[3])
                    vacation_until = None if vacation_enabled else vacation_row[2]
                    vacation_new_since_start = await self._helpdesk_vacation_count(
                        since=vacation_row[1],
                        after=None,
                        until=vacation_until,
                        telegram_chat_id=config.telegram_chat_id,
                    )
                    vacation_new_since_last_review = await self._helpdesk_vacation_count(
                        since=vacation_row[1],
                        after=vacation_row[3],
                        until=vacation_until,
                        telegram_chat_id=config.telegram_chat_id,
                    )
            except Exception:
                await self.session.rollback()
        return {
            "enabled": config.enabled,
            "configured": config.configured,
            "host": "configured" if config.host else "missing",
            "port": config.port,
            "ssl": config.ssl,
            "username": config.safe_username,
            "folder": config.folder,
            "telegram_chat_id": "configured" if config.telegram_chat_id is not None else "missing",
            "missing": ", ".join(config.missing_required) or "none",
            "last_check": await self._redis_text(HELPDESK_LAST_CHECK_KEY),
            "last_success": await self._redis_text(HELPDESK_LAST_SUCCESS_KEY),
            "last_error": await self._redis_text(HELPDESK_LAST_ERROR_KEY, default="none"),
            "baseline": baseline,
            "last_seen_uid": last_seen_uid,
            "mailbox_last_check": mailbox_last_check,
            "mailbox_last_success": mailbox_last_success,
            "mailbox_last_error": mailbox_last_error,
            "processed_last_24h": processed_last_24h,
            "pending_notifications": pending_notifications,
            "failed_notifications": failed_notifications,
            "vacation_enabled": vacation_enabled,
            "vacation_since": vacation_since,
            "vacation_last_reviewed": vacation_last_reviewed,
            "vacation_new_since_start": vacation_new_since_start,
            "vacation_new_since_last_review": vacation_new_since_last_review,
        }

    async def _helpdesk_vacation_count(
        self,
        *,
        since: datetime | None,
        after: datetime | None,
        until: datetime | None,
        telegram_chat_id: int | None,
    ) -> int:
        if self.session is None or since is None or telegram_chat_id is None:
            return 0
        conditions = [
            HelpdeskEmailEvent.notify_status == HELPDESK_VACATION_NOTIFY_STATUS,
            HelpdeskEmailEvent.telegram_chat_id == telegram_chat_id,
            HelpdeskEmailEvent.created_at >= since,
        ]
        if after is not None:
            conditions.append(HelpdeskEmailEvent.created_at > after)
        if until is not None:
            conditions.append(HelpdeskEmailEvent.created_at <= until)
        result = await self.session.execute(
            select(func.count(HelpdeskEmailEvent.id)).where(*conditions)
        )
        return int(result.scalar_one())

    async def _redis_text(self, key: str, *, default: str = "unknown") -> str:
        if self.redis is None:
            return default
        try:
            raw = await self.redis.get(key)
        except Exception:
            return default
        if raw is None:
            return default
        if isinstance(raw, bytes):
            return raw.decode("utf-8", errors="ignore") or default
        return str(raw)


def render_status_html(snapshot: dict[str, Any]) -> str:
    helpdesk = snapshot.get("helpdesk_imap") or {}
    digests = snapshot.get("digests") or {}
    failed_notifications = helpdesk.get("failed_notifications")
    failed_attention = ""
    if _positive_count(failed_notifications):
        failed_attention = "- attention: failed notifications need retry\n"
    return (
        "<b>Jarvis status</b>\n\n"
        f"API: {_state(snapshot['api']['ok'])} ok\n"
        f"PostgreSQL: {_state(snapshot['postgres']['ok'])} {_label(snapshot['postgres']['ok'])}\n"
        f"Redis: {_state(snapshot['redis']['ok'])} {_label(snapshot['redis']['ok'])}\n"
        f"Worker: {_state(snapshot['worker']['ok'])} {_label(snapshot['worker']['ok'])}\n"
        f"Webhook: {_webhook_status(snapshot['webhook'])}\n"
        f"Reminders: {_state(snapshot['reminders']['ok'])} {_label(snapshot['reminders']['ok'])}\n"
        f"LLM provider: {snapshot['provider']['label']}\n"
        f"Draft streaming: {_state(snapshot['draft_streaming']['ok'])} "
        f"{'enabled' if snapshot['draft_streaming']['ok'] else 'disabled'}\n"
        f"Prompt profiles: {_state(snapshot['prompt_profiles']['ok'])} "
        f"{'active' if snapshot['prompt_profiles']['ok'] else 'degraded'}\n"
        f"Access DB: {_state(snapshot['access_db']['ok'])} "
        f"{_label(snapshot['access_db']['ok'])}\n\n"
        "HelpDesk IMAP:\n"
        f"- enabled: {_yes_no(bool(helpdesk.get('enabled', False)))}\n"
        f"- configured: {_yes_no(bool(helpdesk.get('configured', False)))}\n"
        f"- host: {helpdesk.get('host', 'missing')}\n"
        f"- port: {helpdesk.get('port', 'unknown')}\n"
        f"- ssl: {_yes_no(bool(helpdesk.get('ssl', False)))}\n"
        f"- username: {helpdesk.get('username', 'missing')}\n"
        f"- folder: {helpdesk.get('folder', 'INBOX')}\n"
        f"- telegram chat id: {helpdesk.get('telegram_chat_id', 'missing')}\n"
        f"- missing: {helpdesk.get('missing', 'unknown')}\n"
        f"- last check: {helpdesk.get('last_check', 'unknown')}\n"
        f"- last success: {helpdesk.get('last_success', 'unknown')}\n"
        f"- last error: {helpdesk.get('last_error', 'unknown')}\n"
        f"- baseline: {helpdesk.get('baseline', 'not set')}\n"
        f"- last seen uid: {_count(helpdesk.get('last_seen_uid'))}\n"
        f"- mailbox last check: {helpdesk.get('mailbox_last_check', 'unknown')}\n"
        f"- mailbox last success: {helpdesk.get('mailbox_last_success', 'unknown')}\n"
        f"- mailbox last error: {helpdesk.get('mailbox_last_error', 'unknown')}\n"
        f"- processed last 24h: {_count(helpdesk.get('processed_last_24h'))}\n"
        f"- pending notifications: {_count(helpdesk.get('pending_notifications'))}\n"
        f"- failed notifications: {_count(failed_notifications)}\n"
        f"- vacation mode: {_enabled_disabled(helpdesk.get('vacation_enabled'))}\n"
        f"- vacation since: {helpdesk.get('vacation_since', 'unknown')}\n"
        f"- vacation new since start: {_count(helpdesk.get('vacation_new_since_start'))}\n"
        f"- vacation new since last review: "
        f"{_count(helpdesk.get('vacation_new_since_last_review'))}\n"
        f"- vacation last reviewed: {helpdesk.get('vacation_last_reviewed', 'unknown')}\n"
        f"{failed_attention}\n"
        f"{_render_digests_status(digests)}\n"
        "Last checks:\n"
        f"- DB latency: {_latency(snapshot['postgres'].get('latency_ms'))}\n"
        f"- Redis latency: {_latency(snapshot['redis'].get('latency_ms'))}\n"
        f"- Due reminders: {_count(snapshot['reminders'].get('due_count'))}"
    )


def _elapsed_ms(started: float) -> int:
    return max(0, int((perf_counter() - started) * 1000))


def _parse_heartbeat(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="ignore")
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _state(ok: bool) -> str:
    return "✅" if ok else "⚠️"


def _label(ok: bool) -> str:
    return "ok" if ok else "degraded"


def _webhook_status(webhook: dict[str, Any]) -> str:
    if webhook.get("state") == "configured":
        return "✅ configured"
    return "⚠️ unknown (checked by startup self-healing)"


def _latency(value: object) -> str:
    if value is None:
        return "unknown"
    if isinstance(value, int | float | str | bytes | bytearray):
        return f"{int(value)} ms"
    return "unknown"


def _count(value: object) -> str:
    if value is None:
        return "unknown"
    if isinstance(value, int | float | str | bytes | bytearray):
        return str(int(value))
    return "unknown"


def _positive_count(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, int | float | str | bytes | bytearray):
        try:
            return int(value) > 0
        except (TypeError, ValueError):
            return False
    return False


def _iso_or_unknown(value: object) -> str:
    if value is None:
        return "unknown"
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _iso_or_never(value: object) -> str:
    if value is None:
        return "never"
    return _iso_or_unknown(value)


def _render_digests_status(digests: dict[str, Any]) -> str:
    lines = ["Digests:"]
    policies = digests.get("policies")
    if not isinstance(policies, list) or not policies:
        lines.append("- unavailable")
        return "\n".join(lines)
    for policy in policies:
        if not isinstance(policy, dict):
            continue
        enabled = "enabled" if policy.get("enabled") else "disabled"
        key = str(policy.get("key", "unknown"))
        send_time = str(policy.get("send_time", "unknown"))
        timezone = str(policy.get("timezone", "unknown"))
        chat = str(policy.get("chat", "missing"))
        last_sent = str(policy.get("last_sent", "never"))
        lines.append(
            f"- {key}: {enabled}, {send_time} {timezone}, chat {chat}, "
            f"last sent {last_sent}"
        )
    return "\n".join(lines)


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _enabled_disabled(value: object) -> str:
    return "enabled" if bool(value) else "disabled"
