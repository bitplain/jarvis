import importlib.util
import sys
from pathlib import Path


def load_bootstrap_module():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "bootstrap_real_env.py"
    spec = importlib.util.spec_from_file_location("bootstrap_real_env", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["bootstrap_real_env"] = module
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, object]) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict[str, object]:
        return self._payload


class FakeHttpClient:
    def __init__(self) -> None:
        self.posts: list[dict[str, object]] = []

    def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, object] | None = None,
        timeout: float | None = None,
    ) -> FakeResponse:
        assert "openrouter-key" not in url
        assert "secret-token" not in url
        if url.endswith("/getMe"):
            return FakeResponse(
                200,
                {"ok": True, "result": {"id": 42, "is_bot": True, "username": "jarvis_real_bot"}},
            )
        if url.endswith("/getUpdates"):
            return FakeResponse(
                200,
                {
                    "ok": True,
                    "result": [
                        {"message": {"chat": {"type": "private"}, "from": {"id": 100500}}},
                    ],
                },
            )
        if url.endswith("/models"):
            return FakeResponse(
                200,
                {"data": [{"id": "openai/gpt-4o-mini"}, {"id": "other/text-model"}]},
            )
        raise AssertionError(f"unexpected GET URL: {url}")

    def post(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json: dict[str, object] | None = None,
        timeout: float | None = None,
    ) -> FakeResponse:
        assert headers is not None
        assert str(headers.get("Authorization", "")).startswith("Bearer ")
        self.posts.append({"url": url, "json": json or {}})
        return FakeResponse(
            200,
            {"choices": [{"message": {"content": "тест"}}]},
        )


def test_dry_run_does_not_write_generated_values(tmp_path: Path) -> None:
    module = load_bootstrap_module()
    env_path = tmp_path / ".env"
    env_path.write_text("TELEGRAM_BOT_TOKEN=123456:abcdefghijklmnopqrstuvwxyz\n", encoding="utf-8")

    result = module.bootstrap_env(
        env_path,
        tmp_path / ".env.example",
        apply=False,
        http=FakeHttpClient(),
    )

    content = env_path.read_text(encoding="utf-8")
    assert "ADMIN_API_TOKEN=" not in content
    assert result.verdict in {"BLOCKED_NEEDS_REAL_ENV", "BLOCKED_NEEDS_YANDEX_MODEL"}
    assert result.statuses["TELEGRAM_WEBHOOK_SECRET"] == "<generated>"
    assert result.statuses["ADMIN_API_TOKEN"] == "<generated>"
    assert result.statuses["TELEGRAM_BOT_USERNAME"] == "<derived>"


def test_apply_writes_safe_generated_and_derived_values(tmp_path: Path) -> None:
    module = load_bootstrap_module()
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "TELEGRAM_BOT_TOKEN=123456:abcdefghijklmnopqrstuvwxyz",
                "YANDEX_AI_API_KEY=yandex-key",
                "YANDEX_AI_FOLDER_ID=folder123",
                "OPENROUTER_API_KEY=openrouter-key",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = module.bootstrap_env(
        env_path,
        tmp_path / ".env.example",
        apply=True,
        http=FakeHttpClient(),
    )
    parsed = module.parse_env_file(env_path)

    assert result.statuses["TELEGRAM_WEBHOOK_SECRET"] == "<generated>"
    assert module.is_valid_telegram_secret(parsed["TELEGRAM_WEBHOOK_SECRET"])
    assert len(parsed["TELEGRAM_WEBHOOK_SECRET"]) in {48, 64}
    assert parsed["ADMIN_API_TOKEN"]
    assert parsed["TELEGRAM_BOT_USERNAME"] == "jarvis_real_bot"
    assert parsed["ADMIN_TELEGRAM_IDS"] == "100500"
    assert parsed["YANDEX_AI_BASE_URL"] == "https://ai.api.cloud.yandex.net/v1"
    assert parsed["YANDEX_AI_MODEL"] == "gpt://folder123/qwen3-235b-a22b-fp8/latest"
    assert parsed["OPENROUTER_MODEL"] == "openai/gpt-4o-mini"
    sanitized_output = result.render_sanitized()
    assert "yandex-key" not in sanitized_output
    assert "openrouter-key" not in sanitized_output
    assert parsed["ADMIN_API_TOKEN"] not in sanitized_output
    assert parsed["TELEGRAM_WEBHOOK_SECRET"] not in sanitized_output
