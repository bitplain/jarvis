from app.core.config import Settings


def test_config_loads_from_env() -> None:
    settings = Settings(
        telegram_bot_token="token",
        telegram_bot_username="jarvis_bot",
        telegram_webhook_secret="secret",
        admin_telegram_ids="1, 2",
        admin_api_token="admin",
    )

    assert settings.admin_ids == {1, 2}
    assert settings.openrouter_base_url == "https://openrouter.ai/api/v1"
    assert settings.database_url.startswith("postgresql+asyncpg://")
