from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class GroupStabilityReadinessResult:
    statuses: dict[str, str] = field(default_factory=dict)
    verdict: str = "PARTIAL_GROUP_STABILITY_READINESS_NEEDS_FIX"

    def render_sanitized(self) -> str:
        lines = ["Stage 4F-0 Group stability readiness sanitized result:"]
        for key in sorted(self.statuses):
            lines.append(f"{key}: {self.statuses[key]}")
        lines.append(f"verdict: {self.verdict}")
        return "\n".join(lines)


def _read(path: str) -> str:
    target = ROOT / path
    if not target.exists():
        return ""
    return target.read_text(encoding="utf-8")


def _contains(path: str, expected: str) -> bool:
    return expected in _read(path)


def run_readiness() -> GroupStabilityReadinessResult:
    result = GroupStabilityReadinessResult()
    access_source = _read("app/bot/middlewares/access.py")
    group_sink_source = _read("app/bot/streaming/telegram_fallback.py")
    group_handler_source = _read("app/bot/routers/groups.py")
    worker_source = _read("app/workers/jobs.py")
    access_tests = _read("tests/test_access_control.py")
    group_tests = _read("tests/test_group_handler.py")
    sink_tests = _read("tests/test_telegram_group_edit_sink.py")
    worker_tests = _read("tests/test_worker_streaming_jobs.py")
    report = _read("docs/STAGE_4F0_GROUP_STABILITY_REPORT.md")
    report_lower = report.lower()

    result.statuses["private_unauthorized_access_denied"] = (
        "OK"
        if "access_denied_private" in access_source
        and "Доступ запрещён." in access_source
        and "test_private_unauthorized_gets_access_denied" in access_tests
        else "MISSING"
    )
    result.statuses["group_unauthorized_silent"] = (
        "OK"
        if "access_denied_group_silent" in access_source
        and "GROUP_CHAT_TYPES" in access_source
        and "test_group_unauthorized_is_silent" in access_tests
        and "test_group_unauthorized_mention_is_silent" in access_tests
        else "MISSING"
    )
    result.statuses["group_authorized_enqueue_once"] = (
        "OK"
        if "test_group_authorized_mention_enqueues_once" in group_tests
        and '"private": False' in group_handler_source
        else "MISSING"
    )
    result.statuses["group_final_delivery_guard"] = (
        "OK"
        if "self.final_delivered" in group_sink_source
        and "telegram_group_final_already_delivered" in group_sink_source
        and "test_group_final_edit_failure_sends_one_fallback" in sink_tests
        else "MISSING"
    )
    result.statuses["group_message_not_modified_noop"] = (
        "OK"
        if "_is_message_not_modified" in group_sink_source
        and "telegram_group_final_message_not_modified" in group_sink_source
        and "test_group_message_not_modified_is_success" in sink_tests
        else "MISSING"
    )
    result.statuses["group_final_dedup_tests"] = (
        "OK"
        if all(
            name in sink_tests
            for name in [
                "test_group_final_edit_success_sends_no_duplicate",
                "test_group_final_edit_failure_sends_one_fallback",
                "test_group_long_final_split_once",
            ]
        )
        else "MISSING"
    )
    result.statuses["group_provisional_worker_owned"] = (
        "OK"
        if "Принял. Готовлю групповой ответ." in worker_source
        and "await message.answer(\"Принял. Готовлю групповой ответ.\")"
        not in group_handler_source
        and "Принял. Готовлю групповой ответ." in worker_tests
        else "MISSING"
    )
    result.statuses["stage_report"] = (
        "OK"
        if report
        and "PASS_STAGE_4F0_GROUP_STABILITY_READY" in report
        and "live verification checklist" in report_lower
        else "MISSING"
    )

    if all(value == "OK" for value in result.statuses.values()):
        result.verdict = "PASS_GROUP_STABILITY_READINESS"
    return result


def main() -> int:
    result = run_readiness()
    print(result.render_sanitized())  # noqa: T201
    return 0 if result.verdict == "PASS_GROUP_STABILITY_READINESS" else 2


if __name__ == "__main__":
    sys.exit(main())
