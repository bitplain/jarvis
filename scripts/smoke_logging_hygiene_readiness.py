from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class LoggingHygieneReadinessResult:
    statuses: dict[str, str] = field(default_factory=dict)
    verdict: str = "PARTIAL_LOGGING_HYGIENE_READINESS_NEEDS_FIX"

    def render_sanitized(self) -> str:
        lines = ["Logging hygiene readiness sanitized result:"]
        for key in sorted(self.statuses):
            lines.append(f"{key}: {self.statuses[key]}")
        lines.append(f"verdict: {self.verdict}")
        return "\n".join(lines)


def _read(path: str) -> str:
    target = ROOT / path
    if not target.exists():
        return ""
    return target.read_text(encoding="utf-8")


def run_readiness() -> LoggingHygieneReadinessResult:
    result = LoggingHygieneReadinessResult()
    logging_source = _read("app/core/logging.py")
    webhook_setup_source = _read("app/services/telegram_webhook_setup.py")
    worker_settings_source = _read("app/workers/arq_settings.py")
    logging_tests = _read("tests/test_logging_hygiene.py")
    webhook_tests = _read("tests/test_webhook_self_healing_startup.py")
    agents = _read("AGENTS.md")
    railway_docs = _read("docs/RAILWAY_DEPLOY.md")
    report = _read("docs/HOTFIX_LOGGING_HYGIENE_REPORT.md")

    result.statuses["central_redactor"] = (
        "OK"
        if "def redact_secrets(" in logging_source
        and "def redact(" in logging_source
        and "https://api\\.telegram\\.org/bot" in logging_source
        and "LOG_RECORD_STANDARD_ATTRS" in logging_source
        else "MISSING"
    )
    result.statuses["redacting_formatter"] = (
        "OK"
        if "class RedactingFormatter" in logging_source
        and "def formatException" in logging_source
        and "return redact_secrets(rendered)" in logging_source
        and "formatter = RedactingFormatter" in logging_source
        else "MISSING"
    )
    result.statuses["stdout_stderr_split"] = (
        "OK"
        if "logging.StreamHandler(sys.stdout)" in logging_source
        and "logging.StreamHandler(sys.stderr)" in logging_source
        and "MaxLevelFilter(logging.INFO)" in logging_source
        else "MISSING"
    )
    result.statuses["http_client_info_quiet"] = (
        "OK"
        if all(name in logging_source for name in ['"httpx"', '"httpcore"', '"aiohttp"'])
        and "setLevel(logging.WARNING)" in logging_source
        else "MISSING"
    )
    result.statuses["webhook_setup_sanitized"] = (
        "OK"
        if "from app.core.logging import redact" in webhook_setup_source
        and "sanitize_webhook_error" in webhook_setup_source
        and "safe_url_fields" in webhook_setup_source
        else "MISSING"
    )
    result.statuses["worker_logging_hook"] = (
        "OK"
        if "configure_worker_logging" in worker_settings_source
        and "on_startup = configure_worker_logging" in worker_settings_source
        else "MISSING"
    )
    result.statuses["tests"] = (
        "OK"
        if all(
            item in logging_tests
            for item in [
                "test_redact_masks_telegram_bot_api_url",
                "test_redact_masks_httpx_url_object",
                "test_configure_logging_routes_info_to_stdout_and_errors_to_stderr",
                "test_configure_logging_quiets_http_client_info_logs",
                "test_logger_exception_redacts_traceback_secrets",
                "test_logger_error_exc_info_redacts_traceback_secrets",
                "Traceback (most recent call last)",
            ]
        )
        and "test_webhook_setup_result_redacts_telegram_url_and_authorization" in webhook_tests
        else "MISSING"
    )
    result.statuses["docs"] = (
        "OK"
        if "Logging Hygiene" in agents
        and "logging hygiene" in railway_docs.lower()
        and "PASS_HOTFIX_LOGGING_HYGIENE_READY" in report
        else "MISSING"
    )

    if all(value == "OK" for value in result.statuses.values()):
        result.verdict = "PASS_LOGGING_HYGIENE_READINESS"
    return result


def main() -> int:
    result = run_readiness()
    print(result.render_sanitized())  # noqa: T201
    return 0 if result.verdict == "PASS_LOGGING_HYGIENE_READINESS" else 2


if __name__ == "__main__":
    sys.exit(main())
