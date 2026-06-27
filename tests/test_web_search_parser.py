from app.services.web_search.intent import WebSearchIntent, parse_web_search_intent


def test_parse_web_search_explicit_triggers() -> None:
    cases = {
        "найди последние обновления Railway": "последние обновления Railway",
        "найди в интернете погода на сегодня": "погода на сегодня",
        "поищи новые тарифы OpenAI": "новые тарифы OpenAI",
        "проверь в интернете статус Railway": "статус Railway",
        "посмотри в интернете новости Python": "новости Python",
        "что нового по Telegram Bot API": "Telegram Bot API",
        "найди актуальную информацию про Brave Search": "про Brave Search",
    }

    for text, query in cases.items():
        intent = parse_web_search_intent(text)
        assert isinstance(intent, WebSearchIntent)
        assert intent.query == query


def test_parse_web_search_ignores_normal_message() -> None:
    assert parse_web_search_intent("Привет, как дела?") is None
    assert parse_web_search_intent("где купить молоко?") is None
    assert parse_web_search_intent("Кто ты?") is None
    assert parse_web_search_intent("Помоги со списком") is None


def test_parse_web_search_explicit_weather_and_current_phrases() -> None:
    cases = {
        "Покажи погоду в Москве": ("weather", "погода в Москве сегодня", False),
        "покажи погоду Москва": ("weather", "погода Москва сегодня", False),
        "какая погода в Москве сейчас": ("weather", "погода в Москве сейчас", False),
        "погода в Москве сегодня": ("weather", "погода в Москве сегодня", False),
        "покажи курс доллара": ("general", "курс доллара", False),
        "покажи новости про Telegram": ("general", "новости про Telegram", False),
        "найди в интернете погода на сегодня": ("weather", "погода на сегодня", True),
        "найди в интернете новости": ("general", "новости", True),
    }

    for text, (intent_type, query, needs_clarification) in cases.items():
        intent = parse_web_search_intent(text)
        assert isinstance(intent, WebSearchIntent)
        assert intent.intent_type == intent_type
        assert intent.query == query
        assert intent.needs_clarification is needs_clarification


def test_parse_web_search_group_mention_strips_current_bot() -> None:
    intent = parse_web_search_intent(
        "@Home_ai_my_bot найди последние обновления Railway",
        bot_username="Home_ai_my_bot",
    )

    assert isinstance(intent, WebSearchIntent)
    assert intent.query == "последние обновления Railway"


def test_parse_web_search_group_non_mention_is_not_special() -> None:
    intent = parse_web_search_intent("найди последние обновления Railway")

    assert isinstance(intent, WebSearchIntent)
    assert intent.query == "последние обновления Railway"
