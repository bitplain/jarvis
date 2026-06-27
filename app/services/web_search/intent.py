import re
from dataclasses import dataclass


@dataclass(frozen=True)
class WebSearchIntent:
    query: str


TRIGGERS = (
    "найди актуальную информацию",
    "проверь в интернете",
    "посмотри в интернете",
    "что нового по",
    "найди",
    "поищи",
)


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
                return WebSearchIntent(query=query)
            return None
    return None


def _strip_current_bot_mention(text: str, bot_username: str | None) -> str:
    if not bot_username:
        return text
    username = bot_username.strip().lstrip("@")
    if not username:
        return text
    pattern = rf"(?<![A-Za-z0-9_])@{re.escape(username)}(?![A-Za-z0-9_])"
    return re.sub(pattern, "", text, flags=re.IGNORECASE).strip()
