from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from app.bot.routers.commands import render_web_search_settings_text
from app.services.runtime_settings_service import WebSearchProviderName, WebSearchSettings
from app.services.web_search.context_builder import format_web_search_answer_html
from app.services.web_search.intent import parse_web_search_intent
from app.services.web_search.types import SearchResult
from app.services.web_search.url_safety import is_safe_public_http_url

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class WebSearchFollowupFormattingReadinessResult:
    statuses: dict[str, str] = field(default_factory=dict)
    verdict: str = "PARTIAL_WEB_SEARCH_FOLLOWUP_FORMATTING_READINESS_NEEDS_FIX"

    def render_sanitized(self) -> str:
        lines = ["Web search follow-up formatting readiness sanitized result:"]
        for key in sorted(self.statuses):
            lines.append(f"{key}: {self.statuses[key]}")
        lines.append(f"verdict: {self.verdict}")
        return "\n".join(lines)


def _read(path: str) -> str:
    target = ROOT / path
    if not target.exists():
        return ""
    return target.read_text(encoding="utf-8")


async def run_readiness() -> WebSearchFollowupFormattingReadinessResult:
    result = WebSearchFollowupFormattingReadinessResult()
    intent = _read("app/services/web_search/intent.py")
    clarification = _read("app/services/web_search/clarification.py")
    private_router = _read("app/bot/routers/private.py")
    group_router = _read("app/bot/routers/groups.py")
    worker = _read("app/workers/jobs.py")
    service = _read("app/services/web_search/service.py")
    tests = "\n".join(
        _read(path)
        for path in [
            "tests/test_web_search_parser.py",
            "tests/test_web_search_router.py",
            "tests/test_web_search_context_builder.py",
            "tests/test_web_search_service.py",
            "tests/test_worker_jobs.py",
            "tests/test_settings_command.py",
            "tests/test_smoke_web_search_followup_formatting_readiness.py",
        ]
    )

    weather_cases = {
        "Покажи погоду в Москве": "погода в Москве сегодня",
        "покажи погоду Москва": "погода Москва сегодня",
        "какая погода в Москве сейчас": "погода в Москве сейчас",
        "погода в Москве сегодня": "погода в Москве сегодня",
    }
    result.statuses["weather_phrases_route_to_search"] = (
        "OK"
        if all(
            (parsed := parse_web_search_intent(text)) is not None
            and parsed.intent_type == "weather"
            and parsed.query == query
            for text, query in weather_cases.items()
        )
        else "BROKEN"
    )
    result.statuses["current_info_phrases_route_to_search"] = (
        "OK"
        if all(
            parse_web_search_intent(text) is not None
            for text in [
                "покажи курс доллара",
                "покажи новости про Telegram",
                "найди в интернете новости",
            ]
        )
        and parse_web_search_intent("Привет") is None
        and parse_web_search_intent("Кто ты?") is None
        and parse_web_search_intent("Помоги со списком") is None
        else "BROKEN"
    )
    result.statuses["clarification_storage_exists"] = (
        "OK"
        if all(
            token in clarification
            for token in [
                "CLARIFICATION_TTL_SECONDS",
                "web_search:clarification",
                "save_web_search_clarification",
                "pop_web_search_clarification",
                "build_followup_intent",
                "<masked>",
            ]
        )
        else "MISSING"
    )
    result.statuses["cancel_clears_clarification"] = (
        "OK"
        if 'text.strip() == "/cancel"' in private_router
        and "clear_web_search_clarification" in private_router
        else "MISSING"
    )
    formatted = format_web_search_answer_html(
        "**Сейчас:**\n**+17°C**\n<script>alert(1)</script>",
        [SearchResult("<Weather>", "https://example.com/weather", "<script>unsafe</script>")],
    )
    result.statuses["telegram_formatter_removes_raw_markdown"] = (
        "OK"
        if "**" not in formatted
        and "<script>" not in formatted
        and "&lt;script&gt;" in formatted
        and '<a href="https://example.com/weather">' in formatted
        else "BROKEN"
    )
    result.statuses["url_sanitizer_rejects_non_http"] = (
        "OK"
        if not is_safe_public_http_url("javascript:alert(1)")
        and not is_safe_public_http_url("file:///tmp/secret")
        and is_safe_public_http_url("https://example.com")
        else "BROKEN"
    )
    result.statuses["html_send_fallback_exists"] = (
        "OK"
        if "parse_mode=\"HTML\"" in worker
        and "telegram_html_send_failed_using_plain_fallback" in worker
        and "_telegram_html_to_plain_text" in worker
        else "MISSING"
    )
    result.statuses["provider_disabled_ux_not_configured"] = (
        "OK"
        if "Статус: не настроен"
        in render_web_search_settings_text(
            WebSearchSettings(
                enabled=True,
                provider=WebSearchProviderName.DISABLED,
                max_results=5,
            ),
            provider_key_available=True,
        )
        and "Интернет-поиск не настроен" in service
        and "выберите provider" in service
        and "API key" in service
        else "MISSING"
    )
    result.statuses["no_auto_watcher_enabled"] = (
        "OK"
        if "watcher" not in intent.casefold()
        and "auto_search" not in private_router + group_router
        and "parse_web_search_intent" in private_router
        and "parse_web_search_intent" in group_router
        else "BROKEN"
    )
    result.statuses["regression_tests_exist"] = (
        "OK"
        if all(
            token in tests
            for token in [
                "test_private_vague_weather_creates_pending_clarification",
                "test_private_weather_followup_city_triggers_search",
                "test_private_cancel_clears_web_search_clarification",
                "test_worker_web_search_html_send_failure_falls_back_to_plain_text",
                "test_enabled_search_with_disabled_provider_is_config_error",
            ]
        )
        else "MISSING"
    )

    if all(status == "OK" for status in result.statuses.values()):
        result.verdict = "PASS_WEB_SEARCH_FOLLOWUP_FORMATTING_READINESS"
    return result


def main() -> None:
    result = asyncio.run(run_readiness())
    print(result.render_sanitized())  # noqa: T201
    if result.verdict != "PASS_WEB_SEARCH_FOLLOWUP_FORMATTING_READINESS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
