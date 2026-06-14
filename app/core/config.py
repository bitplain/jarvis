from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "local"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    public_base_url: str = "https://example.com"

    telegram_bot_token: str = ""
    telegram_bot_username: str = ""
    telegram_webhook_secret: str = ""
    admin_telegram_ids: str = ""
    admin_api_token: str = ""

    postgres_db: str = "jarvis"
    postgres_user: str = "jarvis"
    postgres_password: str = "jarvis_password_change_me"
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    redis_url: str = "redis://redis:6379/0"

    memory_max_messages: int = Field(default=20, ge=1, le=200)
    llm_primary_provider: str = "yandex"
    llm_fallback_provider: str = "openrouter"
    regular_assistant_enabled: bool = True
    forwarded_message_assistant_enabled: bool = True
    draft_reply_enabled: bool = True
    group_assistant_enabled: bool = True
    guest_mode_enabled: bool = False
    guest_mode_admin_only: bool = True
    guest_mode_max_tokens: int = Field(default=512, ge=1, le=4096)
    business_mode_enabled: bool = False
    business_admin_only: bool = True
    business_reply_enabled: bool = False
    business_reply_trigger: str = "!jarvis"
    business_memory_max_messages: int = Field(default=10, ge=0, le=100)
    business_allowed_connection_ids: str = ""
    business_allowed_chat_ids: str = ""
    streaming_enabled: bool = True
    streaming_private_draft_enabled: bool = True
    streaming_group_fallback_enabled: bool = True
    streaming_draft_update_interval_ms: int = Field(default=800, ge=100, le=30_000)
    streaming_group_edit_interval_ms: int = Field(default=1000, ge=100, le=30_000)
    streaming_min_chars_delta: int = Field(default=120, ge=1, le=5000)
    streaming_max_draft_seconds: int = Field(default=25, ge=1, le=300)
    streaming_send_chat_action_interval_seconds: int = Field(default=4, ge=1, le=30)
    streaming_draft_raw_api_fallback: bool = True

    yandex_ai_base_url: str = ""
    yandex_ai_api_key: str = ""
    yandex_ai_folder_id: str = ""
    yandex_ai_model: str = ""

    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_api_key: str = ""
    openrouter_model: str = ""

    log_level: str = "INFO"

    @property
    def admin_ids(self) -> set[int]:
        ids: set[int] = set()
        for raw_value in self.admin_telegram_ids.split(","):
            value = raw_value.strip()
            if value:
                ids.add(int(value))
        return ids

    @property
    def business_allowed_connections(self) -> set[str]:
        return {
            value
            for raw_value in self.business_allowed_connection_ids.split(",")
            if (value := raw_value.strip())
        }

    @property
    def business_allowed_chats(self) -> set[int]:
        ids: set[int] = set()
        for raw_value in self.business_allowed_chat_ids.split(","):
            value = raw_value.strip()
            if value:
                ids.add(int(value))
        return ids

    @property
    def database_url(self) -> str:
        return (
            "postgresql+asyncpg://"
            f"{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def selected_model(self) -> str:
        if self.llm_primary_provider == "yandex":
            return self.yandex_ai_model
        if self.llm_primary_provider == "openrouter":
            return self.openrouter_model
        return ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
