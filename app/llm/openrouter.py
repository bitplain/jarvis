from app.core.config import Settings
from app.llm.openai_compatible import OpenAICompatibleProvider


class OpenRouterProvider(OpenAICompatibleProvider):
    def __init__(self, settings: Settings) -> None:
        super().__init__(
            name="openrouter",
            base_url=settings.openrouter_base_url,
            api_key=settings.openrouter_api_key,
            model=settings.openrouter_model,
            extra_headers={
                "HTTP-Referer": settings.public_base_url,
                "X-Title": "Jarvis Telegram AI Bot",
            },
        )
