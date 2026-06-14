from collections.abc import Mapping
from typing import Any


def parse_openai_models_response(payload: Mapping[str, Any]) -> list[str]:
    raw_models = payload.get("data", [])
    if not isinstance(raw_models, list):
        return []
    models: list[str] = []
    for item in raw_models:
        if isinstance(item, Mapping) and isinstance(item.get("id"), str):
            models.append(item["id"])
    return models
