from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field
from pathlib import Path

from app.services.memory_service import MemoryService
from app.services.runtime_settings_service import (
    PROMPT_PROFILE_GROUP_KEY,
    PROMPT_PROFILE_PRIVATE_KEY,
    PROMPT_PROFILE_WATCHER_KEY,
    PromptProfile,
    PromptProfileScope,
    RuntimeSettingsService,
)

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class PromptProfilesReadinessResult:
    statuses: dict[str, str] = field(default_factory=dict)
    verdict: str = "PARTIAL_PROMPT_PROFILES_READINESS_NEEDS_FIX"

    def render_sanitized(self) -> str:
        lines = ["Stage 4F-2 prompt profiles readiness sanitized result:"]
        for key in sorted(self.statuses):
            lines.append(f"{key}: {self.statuses[key]}")
        lines.append(f"verdict: {self.verdict}")
        return "\n".join(lines)


class InMemoryRuntimeSettingsRepository:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def get_value(self, key: str) -> str | None:
        return self.values.get(key)

    async def set_value(
        self,
        key: str,
        value: str,
        *,
        updated_by_telegram_id: int | None,
    ) -> None:
        del updated_by_telegram_id
        self.values[key] = value


def _read(path: str) -> str:
    target = ROOT / path
    if not target.exists():
        return ""
    return target.read_text(encoding="utf-8")


async def run_readiness() -> PromptProfilesReadinessResult:
    result = PromptProfilesReadinessResult()
    repository = InMemoryRuntimeSettingsRepository()
    service = RuntimeSettingsService(repository)

    default_profiles = [
        await service.get_prompt_profile(PromptProfileScope.PRIVATE),
        await service.get_prompt_profile(PromptProfileScope.GROUP),
        await service.get_prompt_profile(PromptProfileScope.WATCHER),
    ]
    result.statuses["defaults"] = (
        "OK"
        if default_profiles
        == [PromptProfile.BALANCED, PromptProfile.BALANCED, PromptProfile.BALANCED]
        else "BROKEN"
    )

    saved_private = await service.set_prompt_profile(
        PromptProfileScope.PRIVATE,
        PromptProfile.SHORT.value,
        updated_by_telegram_id=None,
    )
    saved_group = await service.set_prompt_profile(
        PromptProfileScope.GROUP,
        PromptProfile.DEEP.value,
        updated_by_telegram_id=None,
    )
    saved_watcher = await service.set_prompt_profile(
        PromptProfileScope.WATCHER,
        PromptProfile.WATCHER.value,
        updated_by_telegram_id=None,
    )
    result.statuses["runtime_settings_keys"] = (
        "OK"
        if saved_private == PromptProfile.SHORT
        and saved_group == PromptProfile.DEEP
        and saved_watcher == PromptProfile.WATCHER
        and repository.values[PROMPT_PROFILE_PRIVATE_KEY] == "short"
        and repository.values[PROMPT_PROFILE_GROUP_KEY] == "deep"
        and repository.values[PROMPT_PROFILE_WATCHER_KEY] == "watcher"
        else "BROKEN"
    )

    try:
        await service.set_prompt_profile(
            PromptProfileScope.PRIVATE,
            "mira",
            updated_by_telegram_id=None,
        )
    except ValueError:
        result.statuses["invalid_profile"] = "OK"
    else:
        result.statuses["invalid_profile"] = "BROKEN"

    memory_service = MemoryService(repository=object(), max_messages=5)  # type: ignore[arg-type]
    private_prompt = memory_service.build_system_prompt(
        prompt_profile=PromptProfile.SHORT,
        chat_kind="private",
    )
    group_prompt = memory_service.build_system_prompt(
        prompt_profile=PromptProfile.DEEP,
        chat_kind="group",
    )
    result.statuses["prompt_rendering"] = (
        "OK"
        if "Отвечай коротко" in private_prompt
        and "личном чате" in private_prompt
        and "Дай подробный разбор" in group_prompt
        and "не делай вид, что видишь всю историю группы" in group_prompt
        else "BROKEN"
    )

    commands = _read("app/bot/routers/commands.py")
    required_callbacks = [
        "settings:profiles",
        "settings:profiles:private",
        "settings:profiles:group",
        "settings:profiles:watcher",
        "settings:profile:",
        "Профили",
        "Prompt Profiles Jarvis",
    ]
    result.statuses["settings_callbacks"] = (
        "OK" if all(item in commands for item in required_callbacks) else "MISSING"
    )

    worker = _read("app/workers/jobs.py")
    result.statuses["worker_integration"] = (
        "OK"
        if "PromptProfileScope.PRIVATE if is_private else PromptProfileScope.GROUP" in worker
        and "get_prompt_profile(profile_scope)" in worker
        and "prompt_profile=prompt_profile" in worker
        and "chat_kind=profile_scope.value" in worker
        else "MISSING"
    )
    result.statuses["worker_prompt_profile_fallback"] = (
        "OK"
        if "runtime_settings_unavailable_using_balanced_prompt_profile" in worker
        and "PromptProfile.BALANCED" in worker
        and "RuntimeSettingsUnavailable" in worker
        else "MISSING"
    )

    ingress_tests = _read("tests/test_telegram_webhook_ingress.py")
    required_private_ingress_tests = [
        "test_private_start_replies_after_prompt_profiles",
        "test_private_text_admin_enqueues_after_prompt_profiles",
        "test_private_text_allowed_user_enqueues_after_prompt_profiles",
        "test_private_text_unknown_user_denied_after_prompt_profiles",
        "test_prompt_profile_fsm_does_not_capture_normal_private_text",
        "test_webhook_uses_persistent_dispatcher_for_prompt_profile_fsm",
    ]
    result.statuses["private_ingress_regression_tests"] = (
        "OK"
        if all(test_name in ingress_tests for test_name in required_private_ingress_tests)
        else "MISSING"
    )

    private_ingress_smoke = _read("scripts/smoke_private_ingress_readiness.py")
    result.statuses["private_ingress_smoke"] = (
        "OK"
        if "PASS_PRIVATE_INGRESS_READINESS" in private_ingress_smoke
        and "webhook_redis_soft_failure" in private_ingress_smoke
        else "MISSING"
    )

    script = _read("scripts/smoke_prompt_profiles_readiness.py")
    forbidden_get_updates_call = "get" + "Updates("
    result.statuses["no_get_updates"] = (
        "OK" if forbidden_get_updates_call not in script else "BROKEN"
    )

    docs = "\n".join(
        [
            _read("README.md"),
            _read("AGENTS.md"),
            _read("docs/STAGE_4F2_PROMPT_PROFILES_REPORT.md"),
        ]
    )
    required_docs = [
        "Stage 4F-2",
        "Prompt Profiles",
        "prompt_profile_private",
        "prompt_profile_group",
        "prompt_profile_watcher",
        "PASS_PROMPT_PROFILES_READINESS",
    ]
    result.statuses["docs"] = (
        "OK" if all(item in docs for item in required_docs) else "MISSING"
    )

    if all(value == "OK" for value in result.statuses.values()):
        result.verdict = "PASS_PROMPT_PROFILES_READINESS"
    return result


def main() -> int:
    result = asyncio.run(run_readiness())
    print(result.render_sanitized())  # noqa: T201
    return 0 if result.verdict == "PASS_PROMPT_PROFILES_READINESS" else 2


if __name__ == "__main__":
    sys.exit(main())
