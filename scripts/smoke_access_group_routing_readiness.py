from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class AccessGroupRoutingReadinessResult:
    statuses: dict[str, str] = field(default_factory=dict)
    verdict: str = "PARTIAL_ACCESS_GROUP_ROUTING_READINESS_NEEDS_FIX"

    def render_sanitized(self) -> str:
        lines = ["Access group routing readiness sanitized result:"]
        for key in sorted(self.statuses):
            lines.append(f"{key}: {self.statuses[key]}")
        lines.append(f"verdict: {self.verdict}")
        return "\n".join(lines)


def _read(path: str) -> str:
    target = ROOT / path
    if not target.exists():
        return ""
    return target.read_text(encoding="utf-8")


def run_readiness() -> AccessGroupRoutingReadinessResult:
    result = AccessGroupRoutingReadinessResult()
    access_source = _read("app/bot/middlewares/access.py")
    commands_source = _read("app/bot/routers/commands.py")
    repository_source = _read("app/db/repositories/telegram_access.py")
    ingress_tests = _read("tests/test_telegram_webhook_ingress.py")
    repository_tests = _read("tests/test_telegram_access_repository.py")
    report = _read("docs/HOTFIX_ACCESS_GROUP_ROUTING_REPORT.md")

    result.statuses["whoami_bypass_limited"] = (
        "OK"
        if "is_whoami_command" in access_source
        and 'reason="whoami_bypass"' in access_source
        and "Command(\"whoami\")" in commands_source
        and "Ваш Telegram user ID" in commands_source
        else "MISSING"
    )
    result.statuses["from_user_id_access"] = (
        "OK"
        if "user_id = event.from_user.id if event.from_user else None" in access_source
        and '"user_id": 291844566' in ingress_tests
        and "test_group_access_uses_from_user_id" in ingress_tests
        else "MISSING"
    )
    result.statuses["signed_chat_id_access"] = (
        "OK"
        if "entry.telegram_id == event.chat.id" in access_source
        and "chat_id=-5437860232" in ingress_tests
        and "test_group_access_uses_signed_chat_id" in ingress_tests
        else "MISSING"
    )
    result.statuses["allowed_user_and_group"] = (
        "OK"
        if "is_user_allowed = await service.is_allowed_user(user_id)" in access_source
        and "allowed_groups = await service.list_allowed_groups()" in access_source
        and "test_allowed_user_in_allowed_group_mention_enqueues_once" in ingress_tests
        and "test_allowed_user_in_allowed_group_reply_enqueues_once" in ingress_tests
        else "MISSING"
    )
    result.statuses["unknown_group_silent"] = (
        "OK"
        if "decision=\"deny_silent\"" in access_source
        and "telegram_access_denied_group_silent" in access_source
        and "test_unknown_user_in_allowed_group_is_silent" in ingress_tests
        else "MISSING"
    )
    result.statuses["no_trigger_ignored"] = (
        "OK"
        if "decision=\"ignore_no_trigger\"" in access_source
        and "ignored_no_trigger" in access_source
        and "test_allowed_user_without_mention_is_ignored" in ingress_tests
        else "MISSING"
    )
    result.statuses["access_db_error_safe"] = (
        "OK"
        if "access_db_error" in access_source
        and "test_access_db_error_denies_safely" in ingress_tests
        else "MISSING"
    )
    result.statuses["diagnostic_event"] = (
        "OK"
        if "telegram_access_decision" in access_source
        and "chat_type" in access_source
        and "is_mention_or_reply" in access_source
        and "allowed_user" in access_source
        and "access_records[-1].decision == \"allow\"" in ingress_tests
        else "MISSING"
    )
    result.statuses["repository_upsert_safe"] = (
        "OK"
        if "on_conflict_do_nothing" in repository_source
        and "AccessMutationResult.ALREADY_EXISTS" in repository_source
        and "test_repository_upsert_entry_builds_conflict_update_statement"
        in repository_tests
        else "MISSING"
    )
    required_tests = [
        "test_unknown_private_user_whoami_bypasses_access",
        "test_unknown_group_user_whoami_bypasses_access",
        "test_whoami_does_not_enqueue_llm_job",
        "test_allowed_user_in_allowed_group_mention_enqueues_once",
        "test_allowed_user_in_allowed_group_reply_enqueues_once",
        "test_allowed_user_without_mention_is_ignored",
        "test_unknown_user_in_allowed_group_is_silent",
        "test_allowed_user_in_disallowed_group_is_silent",
        "test_group_access_uses_from_user_id",
        "test_group_access_uses_signed_chat_id",
        "test_access_db_error_denies_safely",
    ]
    result.statuses["regression_tests"] = (
        "OK" if all(test_name in ingress_tests for test_name in required_tests) else "MISSING"
    )
    result.statuses["report"] = (
        "OK"
        if "PASS_HOTFIX_ACCESS_GROUP_ROUTING_READY" in report
        and "Live checklist" in report
        else "MISSING"
    )

    if all(value == "OK" for value in result.statuses.values()):
        result.verdict = "PASS_ACCESS_GROUP_ROUTING_READINESS"
    return result


def main() -> int:
    result = run_readiness()
    print(result.render_sanitized())  # noqa: T201
    return 0 if result.verdict == "PASS_ACCESS_GROUP_ROUTING_READINESS" else 2


if __name__ == "__main__":
    sys.exit(main())
