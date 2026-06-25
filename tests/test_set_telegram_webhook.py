import importlib.util
import sys
from pathlib import Path


def load_webhook_module():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "set_telegram_webhook.py"
    spec = importlib.util.spec_from_file_location("set_telegram_webhook", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["set_telegram_webhook"] = module
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    status_code = 200

    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def json(self) -> dict[str, object]:
        return self._payload


class FakeTelegramHttp:
    def __init__(self) -> None:
        self.posts: list[dict[str, object]] = []
        self.gets: list[str] = []

    def post(
        self,
        url: str,
        *,
        json: dict[str, object] | None = None,
        timeout: float | None = None,
    ) -> FakeResponse:
        self.posts.append({"url": url, "json": json or {}})
        return FakeResponse({"ok": True, "description": "ok"})

    def get(self, url: str, *, timeout: float | None = None) -> FakeResponse:
        self.gets.append(url)
        return FakeResponse(
            {
                "ok": True,
                "result": {
                    "url": "https://example.trycloudflare.com/telegram/webhook",
                    "pending_update_count": 0,
                },
            }
        )


def test_set_webhook_uses_public_base_url_and_sanitizes_output(tmp_path: Path) -> None:
    module = load_webhook_module()
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                f"{'TELEGRAM_BOT_TOKEN'}=123456:abcdefghijklmnopqrstuvwxyz",
                "TELEGRAM_WEBHOOK_SECRET=secret-token-value",
                "PUBLIC_BASE_URL=https://example.trycloudflare.com",
                "",
            ]
        ),
        encoding="utf-8",
    )
    http = FakeTelegramHttp()

    result = module.set_webhook(env_path, http=http)

    assert http.posts[0]["url"].endswith("/setWebhook")
    assert http.posts[0]["json"] == {
        "url": "https://example.trycloudflare.com/telegram/webhook",
        "secret_token": "secret-token-value",
    }
    rendered = result.render_sanitized()
    assert "123456:abcdefghijklmnopqrstuvwxyz" not in rendered
    assert "secret-token-value" not in rendered
    assert "webhook_host: example.trycloudflare.com" in rendered
    assert "webhook_path: /telegram/webhook" in rendered


def test_webhook_info_sanitizes_result(tmp_path: Path) -> None:
    module = load_webhook_module()
    env_path = tmp_path / ".env"
    env_path.write_text(
        f"{'TELEGRAM_BOT_TOKEN'}=123456:abcdefghijklmnopqrstuvwxyz\n",
        encoding="utf-8",
    )

    result = module.get_webhook_info(env_path, http=FakeTelegramHttp())

    rendered = result.render_sanitized()
    assert "123456:abcdefghijklmnopqrstuvwxyz" not in rendered
    assert "pending_update_count: 0" in rendered
