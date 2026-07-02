from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_SCOPES = ("offline", "read:profile", "read:sleep", "read:recovery", "read:cycles")


@dataclass
class WhoopOAuthSyncReadinessResult:
    statuses: dict[str, str] = field(default_factory=dict)
    verdict: str = "PARTIAL_WHOOP_OAUTH_SYNC_READINESS_NEEDS_FIX"

    def render_sanitized(self) -> str:
        lines = ["Stage 4 WHOOP OAuth sync readiness sanitized result:"]
        for key in sorted(self.statuses):
            lines.append(f"{key}: {self.statuses[key]}")
        lines.append(f"verdict: {self.verdict}")
        return "\n".join(lines)


def _read(path: str) -> str:
    target = ROOT / path
    if not target.exists():
        return ""
    return target.read_text(encoding="utf-8")


async def run_readiness() -> WhoopOAuthSyncReadinessResult:
    result = WhoopOAuthSyncReadinessResult()
    models = _read("app/db/models.py")
    migrations = "\n".join(path.read_text(encoding="utf-8") for path in _whoop_migrations())
    routes = _read("app/api/routes_whoop.py") + _read("app/main.py")
    commands = _read("app/bot/routers/commands.py")
    client = _read("app/services/whoop_client.py")
    sync = _read("app/services/whoop_sync.py")
    worker = _read("app/workers/jobs.py") + _read("app/workers/arq_settings.py")
    status = _read("app/services/status_service.py")
    docs = "\n".join(
        [
            _read("README.md"),
            _read("docs/ARCHITECTURE.md"),
            _read("AGENTS.md"),
            _read("docs/STAGE_4_WHOOP_OAUTH_SYNC_REPORT.md"),
        ]
    )
    tests = "\n".join(
        [
            _read("tests/test_whoop_oauth_sync.py"),
            _read("tests/test_smoke_whoop_oauth_sync_readiness.py"),
        ]
    )
    all_stage_text = "\n".join([models, migrations, routes, commands, client, sync, worker, docs])

    result.statuses["migrations_exist"] = (
        "OK"
        if all(
            token in models + migrations
            for token in [
                "class WhoopIntegration",
                "whoop_integrations",
                "whoop_sleep_records",
                "whoop_recovery_records",
                "whoop_cycle_records",
                "access_token_encrypted",
                "refresh_token_encrypted",
            ]
        )
        else "MISSING"
    )
    result.statuses["routes_exist"] = (
        "OK"
        if all(
            token in routes
            for token in [
                "/integrations/whoop/oauth/start",
                "/integrations/whoop/oauth/callback",
                "WHOOP_OAUTH_STATE_TTL_SECONDS = 600",
                "whoop:oauth:state:",
                "whoop:oauth:start:",
            ]
        )
        else "MISSING"
    )
    result.statuses["settings_route_exists"] = (
        "OK"
        if all(
            token in commands
            for token in [
                "SETTINGS_CALLBACK_WHOOP",
                "SETTINGS_CALLBACK_WHOOP_CONNECT",
                "SETTINGS_CALLBACK_WHOOP_SYNC",
                "SETTINGS_CALLBACK_WHOOP_DISCONNECT",
                "render_whoop_settings_text",
                "build_whoop_settings_keyboard",
            ]
        )
        else "MISSING"
    )
    result.statuses["client_exists"] = (
        "OK"
        if all(
            token in client
            for token in [
                "WHOOP_AUTHORIZATION_URL",
                "WHOOP_TOKEN_URL",
                "exchange_code_for_tokens",
                "refresh_access_token",
                "get_profile",
                "get_sleep_collection",
                "get_recovery_collection",
                "get_cycle_collection",
                "WhoopRateLimitError",
            ]
        )
        else "MISSING"
    )
    result.statuses["sync_service_exists"] = (
        "OK"
        if all(
            token in sync
            for token in [
                "sync_whoop_user",
                "sync_recent_whoop_data",
                "upsert_sleep_record",
                "upsert_recovery_record",
                "upsert_cycle_record",
                "PENDING_SCORE",
                "UNSCORABLE",
            ]
        )
        else "MISSING"
    )
    result.statuses["worker_cron_exists"] = (
        "OK"
        if all(
            token in worker
            for token in [
                "sync_whoop_integrations",
                "cron(sync_whoop_integrations",
                "whoop:sync:",
                "whoop_enabled",
            ]
        )
        else "MISSING"
    )
    result.statuses["scopes"] = (
        "OK" if all(scope in client + routes + docs for scope in REQUIRED_SCOPES) else "MISSING"
    )
    result.statuses["status_integration"] = (
        "OK"
        if all(token in status for token in ["WHOOP:", "connected integrations", "last error"])
        else "MISSING"
    )
    result.statuses["tests_exist"] = (
        "OK"
        if all(
            token in tests
            for token in [
                "test_whoop_config_defaults_are_disabled_and_safe",
                "test_whoop_client_exchanges_refreshes_and_handles_rate_limits",
                "test_whoop_sync_refreshes_rotated_tokens",
                "test_whoop_oauth_sync_readiness_passes",
            ]
        )
        else "MISSING"
    )
    whoop_worker = _slice_between(
        worker,
        "async def sync_whoop_integrations",
        "async def _claim_helpdesk_ticket_reminder",
    )
    whoop_runtime = "\n".join([client, sync, routes, whoop_worker])
    result.statuses["no_ai_analysis"] = (
        "OK"
        if not re.search(
            r"AI[- ]анализ|анализ сна|sleep analysis|build_llm_provider|LLMMessage",
            whoop_runtime,
        )
        else "BROKEN"
    )
    result.statuses["whoop_digest_card_stage5_boundary"] = (
        "OK"
        if "upsert_latest_whoop_sleep_event" in sync + worker
        and "build_whoop_sleep_card" not in routes + commands
        else "BROKEN"
    )
    result.statuses["official_api_only"] = (
        "OK"
        if all(
            token in all_stage_text
            for token in [
                "https://api.prod.whoop.com/oauth/oauth2/auth",
                "https://api.prod.whoop.com/oauth/oauth2/token",
                "https://api.prod.whoop.com/developer/v2",
                "/activity/sleep",
                "/recovery",
                "/cycle",
            ]
        )
        and not re.search(
            r"app-api|private[-_ ]whoop|reverse[-_ ]engineer|api-7\.whoop",
            whoop_runtime,
        )
        else "BROKEN"
    )
    result.statuses["no_secret_print_patterns"] = (
        "OK"
        if all(
            token not in all_stage_text
            for token in [
                "print(settings.whoop_client_secret",
                "logger.info(settings.whoop_client_secret",
                "logger.warning(settings.whoop_client_secret",
                "print(access_token",
                "print(refresh_token",
                "logger.info(access_token",
                "logger.info(refresh_token",
            ]
        )
        else "BROKEN"
    )

    if all(status == "OK" for status in result.statuses.values()):
        result.verdict = "PASS_WHOOP_OAUTH_SYNC_READINESS"
    return result


def _whoop_migrations() -> list[Path]:
    return sorted((ROOT / "alembic" / "versions").glob("*whoop*.py"))


def _slice_between(text: str, start: str, end: str) -> str:
    start_index = text.find(start)
    if start_index < 0:
        return ""
    end_index = text.find(end, start_index)
    if end_index < 0:
        return text[start_index:]
    return text[start_index:end_index]


def main() -> None:
    result = asyncio.run(run_readiness())
    print(result.render_sanitized())  # noqa: T201
    if result.verdict != "PASS_WHOOP_OAUTH_SYNC_READINESS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
