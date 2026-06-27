from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from app.services.web_search.intent import parse_web_search_intent
from app.services.web_search.url_safety import is_safe_public_http_url

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class WebSearchReadinessResult:
    statuses: dict[str, str] = field(default_factory=dict)
    verdict: str = "PARTIAL_WEB_SEARCH_READINESS_NEEDS_FIX"

    def render_sanitized(self) -> str:
        lines = ["Stage 4K web search readiness sanitized result:"]
        for key in sorted(self.statuses):
            lines.append(f"{key}: {self.statuses[key]}")
        lines.append(f"verdict: {self.verdict}")
        return "\n".join(lines)


def _read(path: str) -> str:
    target = ROOT / path
    if not target.exists():
        return ""
    return target.read_text(encoding="utf-8")


async def run_readiness() -> WebSearchReadinessResult:
    result = WebSearchReadinessResult()
    config = _read("app/core/config.py")
    runtime_settings = _read("app/services/runtime_settings_service.py")
    service = _read("app/services/web_search/service.py")
    provider = _read("app/services/web_search/provider.py")
    tavily = _read("app/services/web_search/tavily.py")
    brave = _read("app/services/web_search/brave.py")
    url_safety = _read("app/services/web_search/url_safety.py")
    context_builder = _read("app/services/web_search/context_builder.py")
    intent = _read("app/services/web_search/intent.py")
    commands = _read("app/bot/routers/commands.py")
    private_router = _read("app/bot/routers/private.py")
    group_router = _read("app/bot/routers/groups.py")
    worker = _read("app/workers/jobs.py")
    migration = _read("alembic/versions/20260627_0011_web_search_cache.py")
    models = _read("app/db/models.py")
    tests = "\n".join(
        _read(path)
        for path in [
            "tests/test_web_search_parser.py",
            "tests/test_web_search_url_safety.py",
            "tests/test_web_search_context_builder.py",
            "tests/test_web_search_service.py",
            "tests/test_web_search_router.py",
            "tests/test_worker_jobs.py",
        ]
    )

    result.statuses["provider_abstraction_exists"] = (
        "OK"
        if "class WebSearchProvider" in provider
        and "class TavilySearchProvider" in tavily
        and "class BraveSearchProvider" in brave
        else "MISSING"
    )
    result.statuses["provider_names_exist"] = (
        "OK"
        if all(token in runtime_settings for token in ["disabled", "tavily", "brave"])
        and all(token in config for token in ["web_search_provider", "tavily_api_key"])
        else "MISSING"
    )
    result.statuses["settings_keys_exist"] = (
        "OK"
        if all(
            token in runtime_settings + commands
            for token in [
                "web_search.enabled",
                "web_search.provider",
                "web_search.max_results",
                "SETTINGS_CALLBACK_WEB_SEARCH",
                "Интернет-поиск",
            ]
        )
        else "MISSING"
    )
    result.statuses["explicit_triggers_exist"] = (
        "OK"
        if all(
            parse_web_search_intent(text) is not None
            for text in [
                "найди последние обновления Railway",
                "поищи новые тарифы OpenAI",
                "проверь в интернете статус Railway",
                "что нового по Telegram Bot API",
            ]
        )
        and "TRIGGERS" in intent
        else "MISSING"
    )
    result.statuses["url_safety_exists"] = (
        "OK"
        if is_safe_public_http_url("https://example.com")
        and not is_safe_public_http_url("http://localhost:8000")
        and not is_safe_public_http_url("http://169.254.169.254/latest/meta-data")
        and "is_safe_public_http_url" in url_safety
        else "BROKEN"
    )
    result.statuses["context_builder_exists"] = (
        "OK"
        if all(token in context_builder for token in ["Найденные источники", "html.escape"])
        else "MISSING"
    )
    result.statuses["cache_migration_exists"] = (
        "OK"
        if all(
            token in migration + models
            for token in ["web_search_cache", "query_hash", "results_json", "expires_at"]
        )
        else "MISSING"
    )
    result.statuses["router_integration_exists"] = (
        "OK"
        if "parse_web_search_intent" in private_router
        and "parse_web_search_intent" in group_router
        and '"web_search"' in private_router + group_router
        else "MISSING"
    )
    result.statuses["llm_context_injection_exists"] = (
        "OK"
        if "build_search_system_prompt" in worker
        and "build_sources_text" in worker
        and "build_web_search_service" in worker
        else "MISSING"
    )
    result.statuses["no_auto_search_or_browser"] = (
        "OK"
        if "parse_web_search_intent" in private_router + group_router
        and "browser" not in service.lower()
        and "selenium" not in service.lower()
        and "playwright" not in service.lower()
        else "BROKEN"
    )
    result.statuses["fake_provider_tests_exist"] = (
        "OK"
        if all(
            token in tests
            for token in [
                "FakeProvider",
                "test_cache_hit_avoids_provider_call",
                "test_worker_web_search_injects_context_and_appends_sources",
                "test_private_normal_message_keeps_generic_llm_path",
            ]
        )
        else "MISSING"
    )

    if all(status == "OK" for status in result.statuses.values()):
        result.verdict = "PASS_WEB_SEARCH_READINESS"
    return result


def main() -> None:
    result = asyncio.run(run_readiness())
    print(result.render_sanitized())  # noqa: T201
    if result.verdict != "PASS_WEB_SEARCH_READINESS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
