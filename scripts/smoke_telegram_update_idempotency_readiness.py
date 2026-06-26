from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class TelegramUpdateIdempotencyReadinessResult:
    statuses: dict[str, str] = field(default_factory=dict)
    verdict: str = "PARTIAL_TELEGRAM_UPDATE_IDEMPOTENCY_READINESS_NEEDS_FIX"

    def render_sanitized(self) -> str:
        lines = ["Telegram update idempotency readiness sanitized result:"]
        for key in sorted(self.statuses):
            lines.append(f"{key}: {self.statuses[key]}")
        lines.append(f"verdict: {self.verdict}")
        return "\n".join(lines)


def _read(path: str) -> str:
    target = ROOT / path
    if not target.exists():
        return ""
    return target.read_text(encoding="utf-8")


def run_readiness() -> TelegramUpdateIdempotencyReadinessResult:
    result = TelegramUpdateIdempotencyReadinessResult()
    webhook_route = _read("app/api/routes_telegram.py")
    private_router = _read("app/bot/routers/private.py")
    group_router = _read("app/bot/routers/groups.py")
    ingress_tests = _read("tests/test_telegram_webhook_ingress.py")
    polling_readiness = _read("scripts/smoke_polling_readiness.py")
    polling_runner = _read("scripts/run_polling.py")
    polling_tests = _read("tests/test_smoke_polling_readiness.py")
    runner_tests = _read("tests/test_run_polling_script.py")

    result.statuses["webhook_update_id_guard"] = (
        "OK"
        if "TELEGRAM_UPDATE_DEDUP_TTL_SECONDS" in webhook_route
        and "telegram:update:{update_id}" in webhook_route
        and "nx=True" in webhook_route
        and "telegram_webhook_duplicate_update_skipped" in webhook_route
        else "MISSING"
    )
    result.statuses["dedup_redis_fail_open"] = (
        "OK"
        if "telegram_webhook_dedup_unavailable" in webhook_route
        and "return True" in webhook_route
        and "test_webhook_dedup_redis_failure_still_feeds_dispatcher" in ingress_tests
        else "MISSING"
    )
    result.statuses["stable_llm_job_id"] = (
        "OK"
        if 'job_id = f"llm:{message.chat.id}:{message.message_id}"' in private_router
        and 'job_id = f"llm:{message.chat.id}:{message.message_id}"' in group_router
        and "_job_id=job_id" in private_router
        and "_job_id=job_id" in group_router
        else "MISSING"
    )
    result.statuses["duplicate_private_test"] = (
        "OK"
        if "test_duplicate_private_update_id_is_accepted_without_second_enqueue" in ingress_tests
        and "telegram_webhook_duplicate_update_skipped" in ingress_tests
        else "MISSING"
    )
    result.statuses["duplicate_group_test"] = (
        "OK"
        if "test_duplicate_group_update_id_is_accepted_without_second_enqueue" in ingress_tests
        else "MISSING"
    )
    result.statuses["duplicate_start_test"] = (
        "OK"
        if "test_duplicate_start_update_id_is_accepted_without_second_reply" in ingress_tests
        else "MISSING"
    )
    result.statuses["production_polling_guard"] = (
        "OK"
        if "SKIPPED production_webhook_runtime" in polling_readiness
        and "PRODUCTION_POLLING_ERROR" in polling_runner
        and "test_polling_readiness_does_not_delete_webhook_in_production" in polling_tests
        and "test_polling_runner_refuses_production_webhook_runtime" in runner_tests
        else "MISSING"
    )

    if all(value == "OK" for value in result.statuses.values()):
        result.verdict = "PASS_TELEGRAM_UPDATE_IDEMPOTENCY_READINESS"
    return result


def main() -> int:
    result = run_readiness()
    print(result.render_sanitized())  # noqa: T201
    return 0 if result.verdict == "PASS_TELEGRAM_UPDATE_IDEMPOTENCY_READINESS" else 2


if __name__ == "__main__":
    sys.exit(main())
