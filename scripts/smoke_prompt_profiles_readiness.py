from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field
from pathlib import Path

from app.services.memory_service import MemoryService
from app.services.runtime_settings_service import (
    DEFAULT_PROMPTS,
    MAX_PROMPT_LENGTH,
    PROMPT_GROUP_KEY,
    PROMPT_PRIVATE_KEY,
    PROMPT_WATCH_KEY,
    PromptProfile,
    PromptProfileScope,
    PromptSource,
    RuntimeSettingsService,
)

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class PromptProfilesReadinessResult:
    statuses: dict[str, str] = field(default_factory=dict)
    verdict: str = "PARTIAL_PROMPT_PROFILES_RAW_EDITOR_READINESS_NEEDS_FIX"

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

    async def delete_value(self, key: str) -> None:
        self.values.pop(key, None)


def _read(path: str) -> str:
    target = ROOT / path
    if not target.exists():
        return ""
    return target.read_text(encoding="utf-8")


async def run_readiness() -> PromptProfilesReadinessResult:
    result = PromptProfilesReadinessResult()
    repository = InMemoryRuntimeSettingsRepository()
    service = RuntimeSettingsService(repository)

    default_prompts = [
        await service.get_prompt(PromptProfileScope.PRIVATE),
        await service.get_prompt(PromptProfileScope.GROUP),
        await service.get_prompt(PromptProfileScope.WATCHER),
    ]
    result.statuses["raw_prompt_defaults"] = (
        "OK"
        if [prompt.source for prompt in default_prompts]
        == [PromptSource.DEFAULT, PromptSource.DEFAULT, PromptSource.DEFAULT]
        and [prompt.text for prompt in default_prompts]
        == [
            DEFAULT_PROMPTS[PromptProfileScope.PRIVATE],
            DEFAULT_PROMPTS[PromptProfileScope.GROUP],
            DEFAULT_PROMPTS[PromptProfileScope.WATCHER],
        ]
        else "BROKEN"
    )

    saved_private = await service.set_prompt(
        PromptProfileScope.PRIVATE,
        "custom private prompt",
        updated_by_telegram_id=None,
    )
    saved_group = await service.set_prompt(
        PromptProfileScope.GROUP,
        "custom group prompt",
        updated_by_telegram_id=None,
    )
    saved_watcher = await service.set_prompt(
        PromptProfileScope.WATCHER,
        "custom watch prompt",
        updated_by_telegram_id=None,
    )
    result.statuses["raw_prompt_runtime_settings_keys"] = (
        "OK"
        if saved_private.source is PromptSource.CUSTOM
        and saved_group.source is PromptSource.CUSTOM
        and saved_watcher.source is PromptSource.CUSTOM
        and repository.values[PROMPT_PRIVATE_KEY] == "custom private prompt"
        and repository.values[PROMPT_GROUP_KEY] == "custom group prompt"
        and repository.values[PROMPT_WATCH_KEY] == "custom watch prompt"
        else "BROKEN"
    )

    reset_private = await service.reset_prompt(PromptProfileScope.PRIVATE)
    result.statuses["raw_prompt_reset"] = (
        "OK"
        if reset_private.source is PromptSource.DEFAULT
        and reset_private.text == DEFAULT_PROMPTS[PromptProfileScope.PRIVATE]
        and PROMPT_PRIVATE_KEY not in repository.values
        else "BROKEN"
    )

    try:
        await service.set_prompt(
            PromptProfileScope.PRIVATE,
            "x" * (MAX_PROMPT_LENGTH + 1),
            updated_by_telegram_id=None,
        )
    except ValueError:
        result.statuses["max_prompt_length"] = "OK"
    else:
        result.statuses["max_prompt_length"] = "BROKEN"

    saved_profile = await service.set_prompt_profile(
        PromptProfileScope.PRIVATE,
        PromptProfile.SHORT.value,
        updated_by_telegram_id=None,
    )
    result.statuses["style_presets_still_separate"] = (
        "OK" if saved_profile == PromptProfile.SHORT else "BROKEN"
    )

    memory_service = MemoryService(repository=object(), max_messages=5)  # type: ignore[arg-type]
    raw_prompt = memory_service.build_system_prompt(system_prompt="raw prompt")
    result.statuses["raw_prompt_rendering"] = (
        "OK" if raw_prompt == "raw prompt" else "BROKEN"
    )
    private_style_prompt = memory_service.build_system_prompt(
        prompt_profile=PromptProfile.SHORT,
        chat_kind="private",
    )
    result.statuses["style_prompt_rendering"] = (
        "OK"
        if "Отвечай коротко" in private_style_prompt
        and "личном чате" in private_style_prompt
        else "BROKEN"
    )

    commands = _read("app/bot/routers/commands.py")
    required_callbacks = [
        "settings:prompts",
        "settings:prompts:private",
        "settings:prompts:group",
        "settings:prompts:watcher",
        "settings:prompt:",
        "Промты Jarvis",
        "Показать полностью",
        "Сбросить",
        "PromptEditorInput",
        "handle_prompt_input_message",
    ]
    result.statuses["settings_callbacks"] = (
        "OK" if all(item in commands for item in required_callbacks) else "MISSING"
    )
    result.statuses["prompt_fsm_state_scoped"] = (
        "OK"
        if "StateFilter(PromptEditorInput.private)" in commands
        and "StateFilter(PromptEditorInput.group)" in commands
        and "StateFilter(PromptEditorInput.watcher)" in commands
        and "handle_cancel_message" in commands
        else "MISSING"
    )
    result.statuses["presets_not_raw_prompt_replacement"] = (
        "OK"
        if "Стиль ответа Jarvis" in commands
        and "Это пресеты стиля ответа, а не редактор raw prompt." in commands
        and "Промты" in commands
        else "MISSING"
    )

    worker = _read("app/workers/jobs.py")
    result.statuses["worker_integration"] = (
        "OK"
        if "PromptProfileScope.PRIVATE if is_private else PromptProfileScope.GROUP" in worker
        and "get_prompt(profile_scope)" in worker
        and "system_prompt=prompt_text" in worker
        else "MISSING"
    )
    result.statuses["worker_prompt_fallback"] = (
        "OK"
        if "runtime_settings_unavailable_using_default_prompt" in worker
        and "DEFAULT_PROMPTS[profile_scope]" in worker
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
        "Промты",
        "prompt.private",
        "prompt.group",
        "prompt.watch",
        "PASS_PROMPT_PROFILES_RAW_EDITOR_READINESS",
    ]
    result.statuses["docs"] = (
        "OK" if all(item in docs for item in required_docs) else "MISSING"
    )

    if all(value == "OK" for value in result.statuses.values()):
        result.verdict = "PASS_PROMPT_PROFILES_RAW_EDITOR_READINESS"
    return result


def main() -> int:
    result = asyncio.run(run_readiness())
    print(result.render_sanitized())  # noqa: T201
    return 0 if result.verdict == "PASS_PROMPT_PROFILES_RAW_EDITOR_READINESS" else 2


if __name__ == "__main__":
    sys.exit(main())
