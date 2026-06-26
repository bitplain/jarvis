from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class MiraPrivateStreamingReadinessResult:
    statuses: dict[str, str] = field(default_factory=dict)
    verdict: str = "PARTIAL_MIRA_PRIVATE_STREAMING_READINESS_NEEDS_FIX"

    def render_sanitized(self) -> str:
        lines = ["Stage 4F-3 Mira private streaming readiness sanitized result:"]
        for key in sorted(self.statuses):
            lines.append(f"{key}: {self.statuses[key]}")
        lines.append(f"verdict: {self.verdict}")
        return "\n".join(lines)


def _read(path: str) -> str:
    target = ROOT / path
    if not target.exists():
        return ""
    return target.read_text(encoding="utf-8")


def _group_streaming_block(worker: str) -> str:
    start = worker.find("async def _process_group_streaming")
    end = worker.find("async def process_llm_message", start)
    if start == -1 or end == -1:
        return ""
    return worker[start:end]


def run_readiness() -> MiraPrivateStreamingReadinessResult:
    result = MiraPrivateStreamingReadinessResult()
    config = _read("app/core/config.py")
    adapter = _read("app/bot/adapters/message_draft_api.py")
    sink = _read("app/bot/streaming/telegram_draft.py")
    worker = _read("app/workers/jobs.py")
    sink_tests = _read("tests/test_telegram_draft_sink.py")
    worker_tests = _read("tests/test_worker_streaming_jobs.py")
    group_block = _group_streaming_block(worker)

    result.statuses["feature_flag"] = (
        "OK"
        if "telegram_private_draft_streaming_enabled: bool = False" in config
        else "MISSING"
    )
    result.statuses["draft_api_wrappers"] = (
        "OK"
        if "async def send_message_draft" in adapter
        and "draft_id: int | None = None" in adapter
        and "async def send_rich_message_draft" in adapter
        and "sendRichMessageDraft" in adapter
        and "rich_message" in adapter
        else "MISSING"
    )
    result.statuses["private_sink_rich_thinking"] = (
        "OK"
        if "THINKING_RICH_MESSAGE" in sink
        and "rich_thinking_enabled" in sink
        and "send_rich_message_draft" in sink
        and "sendRichMessageDraft" in sink
        and "telegram_send_rich_message_draft_called" in sink
        else "MISSING"
    )
    result.statuses["fallback_path"] = (
        "OK"
        if "telegram_private_draft_streaming_failed" in sink
        and "text=THINKING_DRAFT_TEXT" in sink
        and "streaming_private_draft_failed_using_fallback" in worker
        else "MISSING"
    )
    result.statuses["worker_flag_wiring"] = (
        "OK"
        if "rich_thinking_enabled=settings.telegram_private_draft_streaming_enabled" in worker
        and '"mira_style_enabled": settings.telegram_private_draft_streaming_enabled' in worker
        else "MISSING"
    )
    result.statuses["group_path_no_private_draft"] = (
        "OK"
        if group_block
        and "TelegramGroupEditSink" in group_block
        and "TelegramPrivateDraftSink" not in group_block
        and "sendMessageDraft" not in group_block
        and "sendRichMessageDraft" not in group_block
        else "MISSING"
    )
    result.statuses["regression_tests"] = (
        "OK"
        if "test_private_mira_draft_starts_with_rich_thinking_block" in sink_tests
        and "test_private_mira_draft_falls_back_to_text_thinking_when_rich_fails" in sink_tests
        and "test_private_mira_draft_raw_adapter_sends_rich_thinking_block" in sink_tests
        and "test_private_mira_streaming_uses_rich_thinking_then_same_draft_id_updates"
        in worker_tests
        and "test_private_mira_rich_failure_falls_back_to_text_draft_without_job_failure"
        in worker_tests
        and "test_group_streaming_uses_fallback_edit_without_draft_and_private_false"
        in worker_tests
        else "MISSING"
    )

    if all(value == "OK" for value in result.statuses.values()):
        result.verdict = "PASS_MIRA_PRIVATE_STREAMING_READINESS"
    return result


def main() -> int:
    result = run_readiness()
    print(result.render_sanitized())  # noqa: T201
    return 0 if result.verdict == "PASS_MIRA_PRIVATE_STREAMING_READINESS" else 2


if __name__ == "__main__":
    sys.exit(main())
