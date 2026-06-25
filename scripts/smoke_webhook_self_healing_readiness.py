from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class WebhookSelfHealingReadinessResult:
    statuses: dict[str, str] = field(default_factory=dict)
    verdict: str = "PARTIAL_WEBHOOK_SELF_HEALING_READINESS_NEEDS_FIX"

    def render_sanitized(self) -> str:
        lines = ["Telegram webhook self-healing readiness sanitized result:"]
        for key in sorted(self.statuses):
            lines.append(f"{key}: {self.statuses[key]}")
        lines.append(f"verdict: {self.verdict}")
        return "\n".join(lines)


def _read(path: str) -> str:
    target = ROOT / path
    if not target.exists():
        return ""
    return target.read_text(encoding="utf-8")


def run_readiness() -> WebhookSelfHealingReadinessResult:
    result = WebhookSelfHealingReadinessResult()
    main_source = _read("app/main.py")
    setup_service = _read("app/services/telegram_webhook_setup.py")
    setup_script = _read("scripts/set_telegram_webhook.py")
    polling_readiness = _read("scripts/smoke_polling_readiness.py")
    polling_runner = _read("scripts/run_polling.py")
    startup_tests = _read("tests/test_webhook_self_healing_startup.py")
    report = _read("docs/HOTFIX_WEBHOOK_SELF_HEALING_REPORT.md")
    architecture = _read("docs/ARCHITECTURE.md")
    agents = _read("AGENTS.md")

    result.statuses["production_startup_hook"] = (
        "OK"
        if "should_run_startup_webhook_setup(resolved_settings)" in main_source
        and "app.state.startup_webhook_runner(resolved_settings)" in main_source
        else "MISSING"
    )
    result.statuses["shared_setup_logic"] = (
        "OK"
        if "run_startup_webhook_setup" in setup_service
        and "set_webhook_from_values" in setup_service
        and "set_webhook_from_values(load_env_values(env_path)" in setup_script
        else "MISSING"
    )
    result.statuses["production_only_guard"] = (
        "OK"
        if 'settings.app_env.lower() == "production"' in setup_service
        and "test_non_production_startup_does_not_run_webhook_setup" in startup_tests
        else "MISSING"
    )
    result.statuses["non_fatal_failures"] = (
        "OK"
        if "telegram_webhook_setup_failed" in main_source
        and "telegram_webhook_setup_failed" in setup_service
        and "test_missing_webhook_token_does_not_fail_production_startup" in startup_tests
        and "test_webhook_setup_failure_does_not_fail_production_startup" in startup_tests
        else "MISSING"
    )
    result.statuses["sanitized_logs"] = (
        "OK"
        if all(
            item in setup_service
            for item in [
                "telegram_webhook_setup_started",
                "telegram_webhook_setup_completed",
                "telegram_webhook_setup_failed",
                "webhook_host",
                "webhook_path",
            ]
        )
        and "test_webhook_setup_logs_do_not_contain_token" in startup_tests
        else "MISSING"
    )
    result.statuses["worker_no_webhook_setup"] = (
        "OK"
        if "test_worker_startup_does_not_import_webhook_setup" in startup_tests
        and "telegram_webhook_setup" not in _read("app/workers/jobs.py")
        and "telegram_webhook_setup" not in _read("app/workers/arq_settings.py")
        else "MISSING"
    )
    result.statuses["delete_webhook_production_guard"] = (
        "OK"
        if "SKIPPED production_webhook_runtime" in polling_readiness
        and "PRODUCTION_POLLING_ERROR" in polling_runner
        else "MISSING"
    )
    result.statuses["docs"] = (
        "OK"
        if "Webhook self-healing" in report
        and "PASS_WEBHOOK_SELF_HEALING_READY" in report
        and "self-healing" in architecture
        and "self-healing" in agents
        else "MISSING"
    )

    if all(value == "OK" for value in result.statuses.values()):
        result.verdict = "PASS_WEBHOOK_SELF_HEALING_READINESS"
    return result


def main() -> int:
    result = run_readiness()
    print(result.render_sanitized())  # noqa: T201
    return 0 if result.verdict == "PASS_WEBHOOK_SELF_HEALING_READINESS" else 2


if __name__ == "__main__":
    sys.exit(main())
