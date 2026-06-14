from typing import Annotated

from fastapi import APIRouter, Depends, Header

from app.core.config import Settings, get_settings
from app.core.security import require_admin_token
from app.llm.openrouter import OpenRouterProvider
from app.llm.yandex import YandexAIStudioProvider

router = APIRouter(prefix="/admin")


@router.get("/models")
async def admin_models(
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    require_admin_token(settings.admin_api_token, authorization)
    yandex = YandexAIStudioProvider(settings)
    openrouter = OpenRouterProvider(settings)
    return {
        "yandex": await yandex.list_models(),
        "openrouter": await openrouter.list_models(),
        "current_model": settings.selected_model,
        "fallback": {
            "primary": settings.llm_primary_provider,
            "fallback": settings.llm_fallback_provider,
            "enabled": True,
        },
    }
