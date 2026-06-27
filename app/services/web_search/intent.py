import re
from dataclasses import dataclass


@dataclass(frozen=True)
class WebSearchIntent:
    query: str
    intent_type: str = "general"
    needs_clarification: bool = False


TRIGGERS = (
    "найди актуальную информацию",
    "проверь в интернете",
    "посмотри в интернете",
    "что нового по",
    "найди в интернете",
    "поищи в интернете",
    "найди",
    "поищи",
)
WEATHER_WORD = "погода"
WEATHER_WORD_RE = re.compile(r"\bпогод[ауеы]?\b", re.IGNORECASE)
WEATHER_TIME_MARKERS = ("сегодня", "сейчас")
GENERAL_SEARCH_PREFIXES = ("покажи",)
GENERAL_TOPICS = ("курс", "новости", "последние", "актуально")


def parse_web_search_intent(
    text: str | None,
    *,
    bot_username: str | None = None,
) -> WebSearchIntent | None:
    if not text:
        return None
    stripped = _strip_current_bot_mention(text.strip(), bot_username)
    normalized = " ".join(stripped.split())
    lowered = normalized.lower()
    for trigger in TRIGGERS:
        if lowered.startswith(trigger):
            query = normalized[len(trigger) :].strip(" :—-")
            if query:
                return _intent_from_query(query)
            return None
    weather = _parse_weather_phrase(normalized)
    if weather is not None:
        return weather
    general = _parse_general_current_phrase(normalized)
    if general is not None:
        return general
    return None


def _strip_current_bot_mention(text: str, bot_username: str | None) -> str:
    if not bot_username:
        return text
    username = bot_username.strip().lstrip("@")
    if not username:
        return text
    pattern = rf"(?<![A-Za-z0-9_])@{re.escape(username)}(?![A-Za-z0-9_])"
    return re.sub(pattern, "", text, flags=re.IGNORECASE).strip()


def _intent_from_query(query: str) -> WebSearchIntent:
    weather = _normalize_weather_query(query)
    if weather is not None:
        return WebSearchIntent(
            query=weather,
            intent_type="weather",
            needs_clarification=not _weather_query_has_location(weather),
        )
    normalized = _normalize_general_query(query)
    return WebSearchIntent(
        query=normalized,
        intent_type="general",
        needs_clarification=_general_query_needs_clarification(normalized),
    )


def _parse_weather_phrase(text: str) -> WebSearchIntent | None:
    query = _normalize_weather_query(text)
    if query is None:
        return None
    lowered = text.casefold()
    explicit = (
        WEATHER_WORD_RE.search(lowered) is not None
        and any(
            marker in lowered
            for marker in (
                "покажи",
                "какая",
                "найди",
                "поищи",
                "проверь",
                "сейчас",
                "сегодня",
            )
        )
    )
    if not explicit:
        return None
    return WebSearchIntent(
        query=query,
        intent_type="weather",
        needs_clarification=not _weather_query_has_location(query),
    )


def _parse_general_current_phrase(text: str) -> WebSearchIntent | None:
    lowered = text.casefold()
    for prefix in GENERAL_SEARCH_PREFIXES:
        if not lowered.startswith(prefix):
            continue
        query = text[len(prefix) :].strip(" :—-")
        query = _normalize_general_query(query)
        if query.casefold().startswith(GENERAL_TOPICS):
            return WebSearchIntent(
                query=query,
                intent_type="general",
                needs_clarification=_general_query_needs_clarification(query),
            )
    return None


def _normalize_weather_query(text: str) -> str | None:
    normalized = " ".join(text.split()).strip(" :—-")
    lowered = normalized.casefold()
    weather_match = WEATHER_WORD_RE.search(lowered)
    if weather_match is None:
        return None
    for prefix in ("покажи", "какая", "найди", "поищи", "проверь"):
        if lowered.startswith(prefix):
            normalized = normalized[len(prefix) :].strip(" :—-")
            lowered = normalized.casefold()
            break
    if lowered.startswith("в интернете"):
        normalized = normalized[len("в интернете") :].strip(" :—-")
        lowered = normalized.casefold()
    if lowered.startswith("какая"):
        normalized = normalized[len("какая") :].strip(" :—-")
        lowered = normalized.casefold()
    weather_match = WEATHER_WORD_RE.search(lowered)
    if weather_match is None:
        return None
    normalized = f"{WEATHER_WORD}{normalized[weather_match.end() :]}".strip(" :—-")
    lowered = normalized.casefold()
    if not any(marker in lowered for marker in WEATHER_TIME_MARKERS):
        normalized = f"{normalized} сегодня"
    return normalized


def _normalize_general_query(text: str) -> str:
    normalized = " ".join(text.split()).strip(" :—-")
    lowered = normalized.casefold()
    if lowered.startswith("в интернете"):
        normalized = normalized[len("в интернете") :].strip(" :—-")
    return normalized


def _weather_query_has_location(query: str) -> bool:
    lowered = query.casefold()
    tail = lowered
    tail = WEATHER_WORD_RE.sub(" ", tail)
    for token in ("на", "в", "во", "сегодня", "сейчас"):
        tail = re.sub(rf"\b{re.escape(token)}\b", " ", tail)
    return bool(" ".join(tail.split()))


def _general_query_needs_clarification(query: str) -> bool:
    lowered = query.casefold().strip()
    return lowered in {"новости", "последние", "актуально", "курс"}
