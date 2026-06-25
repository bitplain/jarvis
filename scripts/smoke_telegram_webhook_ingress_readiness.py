from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class TelegramWebhookIngressReadinessResult:
    statuses: dict[str, str] = field(default_factory=dict)
    verdict: str = "PARTIAL_TELEGRAM_WEBHOOK_INGRESS_READINESS_NEEDS_FIX"

    def render_sanitized(self) -> str:
        lines = ["Telegram webhook ingress readiness sanitized result:"]
        for key in sorted(self.statuses):
            lines.append(f"{key}: {self.statuses[key]}")
        lines.append(f"verdict: {self.verdict}")
        return "\n".join(lines)


def _read(path: str) -> str:
    target = ROOT / path
    if not target.exists():
        return ""
    return target.read_text(encoding="utf-8")


def run_readiness() -> TelegramWebhookIngressReadinessResult:
    result = TelegramWebhookIngressReadinessResult()
    routes_source = _read("app/api/routes_telegram.py")
    main_source = _read("app/main.py")
    webhook_script = _read("scripts/set_telegram_webhook.py")
    webhook_setup_service = _read("app/services/telegram_webhook_setup.py")
    polling_readiness = _read("scripts/smoke_polling_readiness.py")
    polling_runner = _read("scripts/run_polling.py")
    ingress_tests = _read("tests/test_telegram_webhook_ingress.py")
    polling_tests = _read("tests/test_smoke_polling_readiness.py")
    runner_tests = _read("tests/test_run_polling_script.py")
    railway_doc = _read("docs/RAILWAY_DEPLOY.md")
    readme = _read("README.md")
    report = _read("docs/HOTFIX_TELEGRAM_WEBHOOK_SILENT_AFTER_4F0_REPORT.md")

    result.statuses["webhook_route_code"] = (
        "OK"
        if 'APIRouter(prefix="/telegram")' in routes_source
        and '@router.post("/webhook")' in routes_source
        else "MISSING"
    )
    result.statuses["webhook_router_included"] = (
        "OK" if "app.include_router(routes_telegram.router)" in main_source else "MISSING"
    )
    result.statuses["route_map_test"] = (
        "OK" if "test_route_map_contains_webhook_health_and_ready" in ingress_tests else "MISSING"
    )
    result.statuses["private_authorized_ingress_test"] = (
        "OK"
        if "test_webhook_private_admin_update_enqueues_once" in ingress_tests
        and '"private": True' in ingress_tests
        else "MISSING"
    )
    result.statuses["private_unauthorized_ingress_test"] = (
        "OK"
        if "test_webhook_private_unauthorized_gets_access_denied_without_job" in ingress_tests
        and "Доступ запрещён." in ingress_tests
        else "MISSING"
    )
    result.statuses["group_authorized_ingress_test"] = (
        "OK"
        if "test_webhook_group_admin_mention_enqueues_once" in ingress_tests
        and '"private": False' in ingress_tests
        else "MISSING"
    )
    result.statuses["group_unauthorized_silent_ingress_test"] = (
        "OK"
        if "test_webhook_group_unauthorized_is_silent_without_job" in ingress_tests
        and "bot.sent_messages == []" in ingress_tests
        else "MISSING"
    )
    result.statuses["webhook_setup_path"] = (
        "OK"
        if 'return f"{public_base_url.rstrip(\'/\')}/telegram/webhook"' in webhook_setup_service
        and "set_webhook_from_values" in webhook_script
        and "/telegram/webhook" in railway_doc
        and "POST /telegram/webhook" in readme
        else "MISSING"
    )
    result.statuses["production_polling_readiness_guard"] = (
        "OK"
        if "SKIPPED production_webhook_runtime" in polling_readiness
        and "test_polling_readiness_does_not_delete_webhook_in_production" in polling_tests
        else "MISSING"
    )
    result.statuses["production_polling_runner_guard"] = (
        "OK"
        if "PRODUCTION_POLLING_ERROR" in polling_runner
        and "test_polling_runner_refuses_production_webhook_runtime" in runner_tests
        else "MISSING"
    )
    result.statuses["hotfix_report"] = (
        "OK"
        if report
        and "PASS_HOTFIX_TELEGRAM_WEBHOOK_INGRESS_READY" in report
        and "deleteWebhook" in report
        else "MISSING"
    )

    if all(value == "OK" for value in result.statuses.values()):
        result.verdict = "PASS_TELEGRAM_WEBHOOK_INGRESS_READINESS"
    return result


def main() -> int:
    result = run_readiness()
    print(result.render_sanitized())  # noqa: T201
    return 0 if result.verdict == "PASS_TELEGRAM_WEBHOOK_INGRESS_READINESS" else 2


if __name__ == "__main__":
    sys.exit(main())
