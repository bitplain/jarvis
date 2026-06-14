from app.llm.model_discovery import parse_openai_models_response


def test_model_discovery_parses_yandex_and_openrouter_responses() -> None:
    payload = {"data": [{"id": "model-a"}, {"id": "model-b"}]}

    assert parse_openai_models_response(payload) == ["model-a", "model-b"]
