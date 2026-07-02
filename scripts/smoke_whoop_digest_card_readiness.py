from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class WhoopDigestCardReadinessResult:
    statuses: dict[str, str] = field(default_factory=dict)
    verdict: str = "PARTIAL_WHOOP_DIGEST_CARD_READINESS_NEEDS_FIX"

    def render_sanitized(self) -> str:
        lines = ["Stage 5 WHOOP digest card readiness sanitized result:"]
        for key in sorted(self.statuses):
            lines.append(f"{key}: {self.statuses[key]}")
        lines.append(f"verdict: {self.verdict}")
        return "\n".join(lines)


def _read(path: str) -> str:
    target = ROOT / path
    if not target.exists():
        return ""
    return target.read_text(encoding="utf-8")


async def run_readiness() -> WhoopDigestCardReadinessResult:
    result = WhoopDigestCardReadinessResult()
    whoop_cards = _read("app/services/whoop_cards.py")
    whoop_sync = _read("app/services/whoop_sync.py")
    whoop_repository = _read("app/db/repositories/whoop.py")
    event_items = _read("app/services/event_items.py") + _read(
        "app/db/repositories/event_items.py"
    )
    digests = _read("app/services/digests.py")
    event_inbox = _read("app/bot/routers/event_inbox.py")
    client = _read("app/services/whoop_client.py")
    docs = "\n".join(
        [
            _read("README.md"),
            _read("docs/ARCHITECTURE.md"),
            _read("AGENTS.md"),
            _read("docs/STAGE_5_WHOOP_DIGEST_CARD_REPORT.md"),
        ]
    )
    tests = "\n".join(
        [
            _read("tests/test_whoop_cards.py"),
            _read("tests/test_whoop_oauth_sync.py"),
            _read("tests/test_smoke_whoop_digest_card_readiness.py"),
        ]
    )

    result.statuses["service_exists"] = (
        "OK"
        if all(
            token in whoop_cards
            for token in [
                "build_whoop_sleep_card",
                "upsert_latest_whoop_sleep_event",
                "WHOOP_SLEEP_CARD_TYPE = \"whoop_sleep\"",
                "WHOOP_SLEEP_EVENT_SOURCE = \"whoop\"",
                "WHOOP_SLEEP_LOOKBACK_HOURS = 72",
            ]
        )
        else "MISSING"
    )
    result.statuses["event_upsert_identity"] = (
        "OK"
        if all(
            token in event_items + whoop_cards
            for token in [
                "upsert_event_by_payload_identity",
                "get_by_payload_identity",
                "update_from_event",
                "\"identity_key\"",
                "whoop_sleep:",
            ]
        )
        else "MISSING"
    )
    result.statuses["personal_scope_only"] = (
        "OK"
        if "scope=EventScope.PERSONAL" in whoop_cards
        and "event_type=EventType.WHOOP_SLEEP" in whoop_cards
        and "scope=EventScope.WORK" not in whoop_cards
        and "WORK_START_DIGEST_KEY" not in whoop_cards
        else "BROKEN"
    )
    result.statuses["sync_hook"] = (
        "OK"
        if "upsert_latest_whoop_sleep_event" in whoop_sync
        and "event_repository=EventItemRepository" in whoop_sync
        and "mark_sync_success" in whoop_sync
        else "MISSING"
    )
    result.statuses["whoop_repository_reads"] = (
        "OK"
        if all(
            token in whoop_repository
            for token in [
                "list_recent_sleep_records",
                "get_recovery_by_cycle_id",
                "WhoopSleepRecord.start_at",
                "WhoopRecoveryRecord.cycle_id",
            ]
        )
        else "MISSING"
    )
    result.statuses["digest_and_inbox_scope_paths"] = (
        "OK"
        if all(
            token in digests + event_inbox
            for token in [
                "EventScope.PERSONAL",
                "EventScope.HOUSEHOLD",
                "EventScope.WORK",
                "list_for_inbox",
                "list_for_work",
                "list_for_digest",
            ]
        )
        else "MISSING"
    )
    result.statuses["no_ai_or_medical_analysis"] = (
        "OK"
        if not re.search(
            r"build_llm_provider|LLMMessage|AI[- ]анализ|анализ сна|diagnos|диагноз|лечение|болез",
            whoop_cards + whoop_sync,
            flags=re.IGNORECASE,
        )
        else "BROKEN"
    )
    result.statuses["official_api_only"] = (
        "OK"
        if "https://api.prod.whoop.com/developer/v2" in client
        and not re.search(
            r"app-api|private[-_ ]whoop|reverse[-_ ]engineer|api-7\.whoop",
            client + whoop_cards + whoop_sync,
            flags=re.IGNORECASE,
        )
        else "BROKEN"
    )
    result.statuses["no_raw_json_rendering"] = (
        "OK"
        if not re.search(
            r"(card_json|payload_json)\s*=.*raw_json|\"raw_json\"\s*:",
            whoop_cards,
        )
        and "render_card_to_telegram_text" not in whoop_cards
        else "BROKEN"
    )
    result.statuses["tests_exist"] = (
        "OK"
        if all(
            token in tests
            for token in [
                "test_build_whoop_sleep_card_scored_sleep_and_recovery_builds_facts",
                "test_upsert_latest_whoop_sleep_event_creates_one_personal_event_and_digest_item",
                "test_upsert_latest_whoop_sleep_event_updates_done_pending_to_scored",
                "test_upsert_latest_whoop_sleep_event_noops_without_non_nap_sleep_records",
                "test_whoop_sync_success_upserts_sleep_event_from_synced_raw_records",
                "test_whoop_digest_card_readiness_passes",
            ]
        )
        else "MISSING"
    )
    result.statuses["docs"] = (
        "OK"
        if all(
            token in docs
            for token in [
                "Stage 5: WHOOP card",
                "personal-only",
                "work digest",
                "No AI analysis",
                "No medical advice",
                "Stage 6",
            ]
        )
        else "MISSING"
    )

    if all(status == "OK" for status in result.statuses.values()):
        result.verdict = "PASS_WHOOP_DIGEST_CARD_READINESS"
    return result


def main() -> None:
    result = asyncio.run(run_readiness())
    print(result.render_sanitized())  # noqa: T201
    if result.verdict != "PASS_WHOOP_DIGEST_CARD_READINESS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
