from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class PrivateIngressReadinessResult:
    statuses: dict[str, str] = field(default_factory=dict)
    verdict: str = "PARTIAL_PRIVATE_INGRESS_READINESS_NEEDS_FIX"

    def render_sanitized(self) -> str:
        lines = ["Private ingress readiness sanitized result:"]
        for key in sorted(self.statuses):
            lines.append(f"{key}: {self.statuses[key]}")
        lines.append(f"verdict: {self.verdict}")
        return "\n".join(lines)


def _read(path: str) -> str:
    target = ROOT / path
    if not target.exists():
        return ""
    return target.read_text(encoding="utf-8")


def run_readiness() -> PrivateIngressReadinessResult:
    result = PrivateIngressReadinessResult()
    commands = _read("app/bot/routers/commands.py")
    private_router = _read("app/bot/routers/private.py")
    dispatcher = _read("app/bot/dispatcher.py")
    webhook_route = _read("app/api/routes_telegram.py")
    ingress_tests = _read("tests/test_telegram_webhook_ingress.py")
    fsm_tests = _read("tests/test_access_settings_fsm_ingress.py")
    worker = _read("app/workers/jobs.py")
    prompt_smoke = _read("scripts/smoke_prompt_profiles_readiness.py")

    result.statuses["start_handler_exists"] = (
        "OK"
        if "async def cmd_start" in commands
        and 'router.message(Command("start"))(cmd_start)' in commands
        and "Jarvis готов. Пишите вопрос на русском языке." in commands
        else "MISSING"
    )
    result.statuses["private_text_handler_exists"] = (
        "OK"
        if "async def handle_private_text" in private_router
        and 'router.message(F.chat.type == "private")(handle_private_text)' in private_router
        and '"process_llm_message"' in private_router
        and '"private": True' in private_router
        else "MISSING"
    )
    result.statuses["dispatcher_router_order"] = (
        "OK"
        if "dispatcher.include_router(commands.build_router())" in dispatcher
        and "dispatcher.include_router(private.build_router())" in dispatcher
        and dispatcher.index("commands.build_router")
        < dispatcher.index("private.build_router")
        else "MISSING"
    )
    result.statuses["prompt_profile_fsm_filters_state_scoped"] = (
        "OK"
        if "class TelegramAccessInput" in commands
        and "StateFilter(TelegramAccessInput.add_user)" in commands
        and "StateFilter(TelegramAccessInput.remove_user)" in commands
        and "StateFilter(TelegramAccessInput.add_group)" in commands
        and "StateFilter(TelegramAccessInput.remove_group)" in commands
        and "StateFilter(None)" not in commands
        else "BROKEN"
    )
    result.statuses["webhook_persistent_dispatcher"] = (
        "OK"
        if 'getattr(request.app.state, "dispatcher", None)' in webhook_route
        and "request.app.state.dispatcher = dispatcher" in webhook_route
        else "MISSING"
    )
    result.statuses["webhook_redis_soft_failure"] = (
        "OK"
        if "telegram_webhook_redis_unavailable" in webhook_route
        and "redis = None" in webhook_route
        and "request.app.state.redis_pool = redis" in webhook_route
        else "MISSING"
    )
    required_ingress_tests = [
        "test_private_start_replies_after_prompt_profiles",
        "test_private_start_replies_when_redis_pool_is_unavailable",
        "test_private_text_admin_enqueues_after_prompt_profiles",
        "test_private_text_allowed_user_enqueues_after_prompt_profiles",
        "test_private_text_unknown_user_denied_after_prompt_profiles",
        "test_prompt_profile_fsm_does_not_capture_normal_private_text",
        "test_webhook_uses_persistent_dispatcher_for_prompt_profile_fsm",
        "test_whoami_does_not_enqueue_llm_job",
        "test_allowed_user_in_allowed_group_mention_enqueues_once",
    ]
    result.statuses["private_ingress_regression_tests"] = (
        "OK"
        if all(test_name in ingress_tests for test_name in required_ingress_tests)
        else "MISSING"
    )
    result.statuses["access_fsm_intercepts_only_active_state"] = (
        "OK"
        if "test_add_user_state_intercepts_text_before_private_llm" in fsm_tests
        and "test_cancel_clears_access_fsm_state" in fsm_tests
        and '"process_llm_message"' in fsm_tests
        else "MISSING"
    )
    result.statuses["worker_prompt_fallback"] = (
        "OK"
        if "get_prompt(profile_scope)" in worker
        and "RuntimeSettingsUnavailable" in worker
        and "DEFAULT_PROMPTS[profile_scope]" in worker
        and "runtime_settings_unavailable_using_default_prompt" in worker
        else "MISSING"
    )
    result.statuses["prompt_profiles_smoke_covers_private_ingress"] = (
        "OK"
        if "private_ingress_regression_tests" in prompt_smoke
        and "worker_prompt_fallback" in prompt_smoke
        else "MISSING"
    )

    if all(value == "OK" for value in result.statuses.values()):
        result.verdict = "PASS_PRIVATE_INGRESS_READINESS"
    return result


def main() -> int:
    result = run_readiness()
    print(result.render_sanitized())  # noqa: T201
    return 0 if result.verdict == "PASS_PRIVATE_INGRESS_READINESS" else 2


if __name__ == "__main__":
    sys.exit(main())
