from app.core.config import Settings
from app.llm.openai_compatible import OpenAICompatibleProvider


class YandexAIStudioProvider(OpenAICompatibleProvider):
    def __init__(self, settings: Settings) -> None:
        headers: dict[str, str] = {}
        if settings.yandex_ai_folder_id:
            headers["x-folder-id"] = settings.yandex_ai_folder_id
        super().__init__(
            name="yandex",
            base_url=settings.yandex_ai_base_url,
            api_key=settings.yandex_ai_api_key,
            model=settings.yandex_ai_model,
            extra_headers=headers,
        )
