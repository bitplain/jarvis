from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OLD_PRIVATE_TEXT = "Принял. " "Готовлю ответ."
OLD_GROUP_TEXT = "Принял. " "Готовлю групповой ответ."


@dataclass
class ThinkingTextReadinessResult:
    statuses: dict[str, str] = field(default_factory=dict)
    verdict: str = "PARTIAL_THINKING_TEXT_READINESS_NEEDS_FIX"

    @property
    def ok(self) -> bool:
        return self.verdict == "PASS_THINKING_TEXT_READINESS"

    def render(self) -> str:
        lines = ["Stage 4F-4 thinking text readiness sanitized result:"]
        for key in sorted(self.statuses):
            lines.append(f"{key}: {self.statuses[key]}")
        lines.append(f"verdict: {self.verdict}")
        return "\n".join(lines)

    def render_sanitized(self) -> str:
        return self.render()


def _read(path: str) -> str:
    target = ROOT / path
    if not target.exists():
        return ""
    return target.read_text(encoding="utf-8")


def _current_sources() -> dict[str, str]:
    paths = [
        "AGENTS.md",
        "README.md",
        "app/bot/routers/private.py",
        "app/bot/streaming/telegram_draft.py",
        "app/bot/streaming/telegram_fallback.py",
        "app/bot/thinking.py",
        "app/workers/jobs.py",
        "docs/ARCHITECTURE.md",
        "docs/STAGE_4F3_MIRA_PRIVATE_STREAMING_REPORT.md",
        "docs/STAGE_4F4_THINKING_TEXT_CLEANUP_REPORT.md",
        "scripts/smoke_group_stability_readiness.py",
        "tests/test_access_settings_fsm_ingress.py",
        "tests/test_settings_command.py",
        "tests/test_telegram_group_edit_sink.py",
        "tests/test_telegram_webhook_ingress.py",
        "tests/test_worker_streaming_jobs.py",
    ]
    return {path: _read(path) for path in paths}


def _old_text_absent(sources: dict[str, str]) -> bool:
    return all(
        OLD_PRIVATE_TEXT not in source and OLD_GROUP_TEXT not in source
        for source in sources.values()
    )


def run_readiness() -> ThinkingTextReadinessResult:
    result = ThinkingTextReadinessResult()
    sources = _current_sources()
    thinking = sources["app/bot/thinking.py"]
    private_router = sources["app/bot/routers/private.py"]
    draft_sink = sources["app/bot/streaming/telegram_draft.py"]
    fallback_sink = sources["app/bot/streaming/telegram_fallback.py"]
    worker = sources["app/workers/jobs.py"]
    ingress_tests = sources["tests/test_telegram_webhook_ingress.py"]
    worker_tests = sources["tests/test_worker_streaming_jobs.py"]
    group_sink_tests = sources["tests/test_telegram_group_edit_sink.py"]
    access_tests = sources["tests/test_access_settings_fsm_ingress.py"]
    settings_tests = sources["tests/test_settings_command.py"]

    result.statuses["thinking_constant"] = (
        "OK"
        if 'THINKING_TEXT = "Думаю"' in thinking
        and "THINKING_RICH_MESSAGE" in thinking
        and "THINKING_TEXT" in private_router
        and "THINKING_TEXT" in draft_sink
        and "THINKING_TEXT" in fallback_sink
        else "MISSING"
    )
    result.statuses["old_text_absent_current_sources"] = (
        "OK" if _old_text_absent(sources) else "MISSING"
    )
    result.statuses["private_mira_no_regular_ack"] = (
        "OK"
        if "telegram_private_draft_streaming_enabled" in private_router
        and "await message.answer(THINKING_TEXT)" in private_router
        else "MISSING"
    )
    result.statuses["private_fallback_thinking_text"] = (
        "OK"
        if 'assert [message["text"] for message in bot.sent_messages] == ["Думаю"]'
        in ingress_tests
        and '"text": "Думаю"' in worker_tests
        else "MISSING"
    )
    result.statuses["group_provisional_thinking"] = (
        "OK"
        if "provisional_text: str = THINKING_TEXT" in fallback_sink
        and "provisional_text=" not in worker
        and '"text": "Думаю"' in worker_tests
        and '"text": "Думаю"' in group_sink_tests
        else "MISSING"
    )
    result.statuses["group_path_no_draft_api"] = (
        "OK"
        if "test_group_streaming_uses_fallback_edit_without_draft_and_private_false"
        in worker_tests
        and "assert bot.drafts == []" in worker_tests
        and "assert bot.rich_drafts == []" in worker_tests
        else "MISSING"
    )
    result.statuses["private_mira_no_regular_ack_test"] = (
        "OK"
        if "test_private_mira_ingress_enqueues_without_regular_thinking_message"
        in ingress_tests
        and "assert bot.sent_messages == []" in ingress_tests
        else "MISSING"
    )
    result.statuses["group_provisional_thinking_test"] = (
        "OK"
        if "test_group_streaming_uses_fallback_edit_without_draft_and_private_false"
        in worker_tests
        and '"text": "Думаю"' in worker_tests
        else "MISSING"
    )
    result.statuses["commands_and_fsm_no_thinking"] = (
        "OK"
        if "test_private_start_replies_after_prompt_profiles" in ingress_tests
        and "test_whoami_does_not_enqueue_llm_job" in ingress_tests
        and "Думаю" in access_tests
        and '"Думаю" not in message.answers[0]["text"]' in settings_tests
        else "MISSING"
    )

    if all(value == "OK" for value in result.statuses.values()):
        result.verdict = "PASS_THINKING_TEXT_READINESS"
    return result


def main() -> int:
    result = run_readiness()
    print(result.render_sanitized())  # noqa: T201
    return 0 if result.ok else 2


if __name__ == "__main__":
    sys.exit(main())
