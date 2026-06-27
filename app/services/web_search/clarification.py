import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

from app.services.web_search.intent import WebSearchIntent, parse_web_search_intent

logger = logging.getLogger(__name__)

CLARIFICATION_TTL_SECONDS = 10 * 60
CLARIFICATION_KIND = "web_search_clarification"
WEATHER_CLARIFICATION_MESSAGE = "Укажите город или страну для прогноза погоды."
GENERAL_CLARIFICATION_MESSAGE = "Уточните тему для интернет-поиска."
SECRET_LIKE_RE = re.compile(
    r"\b(api[_\s-]?key|authorization|bearer|password|passwd|token|secret)\b",
    re.I,
)


@dataclass(frozen=True)
class WebSearchClarification:
    intent_type: str
    original_query: str
    created_at: float


def web_search_clarification_key(
    *,
    private: bool,
    chat_id: int,
    user_id: int,
) -> str:
    scope = "private" if private else "group"
    return f"web_search:clarification:{scope}:{chat_id}:{user_id}"


def clarification_prompt(intent: WebSearchIntent) -> str:
    if intent.intent_type == "weather":
        return WEATHER_CLARIFICATION_MESSAGE
    return GENERAL_CLARIFICATION_MESSAGE


async def save_web_search_clarification(
    redis: object,
    *,
    private: bool,
    chat_id: int,
    user_id: int,
    intent: WebSearchIntent,
    now: float | None = None,
) -> None:
    if not hasattr(redis, "set"):
        return
    key = web_search_clarification_key(private=private, chat_id=chat_id, user_id=user_id)
    payload = {
        "kind": CLARIFICATION_KIND,
        "intent_type": intent.intent_type,
        "original_query": _safe_store_query(intent.query),
        "created_at": now or time.time(),
    }
    try:
        await redis.set(  # type: ignore[attr-defined]
            key,
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            ex=CLARIFICATION_TTL_SECONDS,
        )
    except Exception as exc:
        logger.warning(
            "web_search_clarification_unavailable",
            extra={"operation": "set", "error_type": type(exc).__name__},
        )


async def pop_web_search_clarification(
    redis: object,
    *,
    private: bool,
    chat_id: int,
    user_id: int,
    now: float | None = None,
) -> WebSearchClarification | None:
    if not hasattr(redis, "get"):
        return None
    key = web_search_clarification_key(private=private, chat_id=chat_id, user_id=user_id)
    try:
        raw = await redis.get(key)  # type: ignore[attr-defined]
    except Exception as exc:
        logger.warning(
            "web_search_clarification_unavailable",
            extra={"operation": "get", "error_type": type(exc).__name__},
        )
        return None
    if raw is None:
        return None
    clarification = _decode_clarification(raw)
    current = now or time.time()
    if clarification is None or current - clarification.created_at > CLARIFICATION_TTL_SECONDS:
        await clear_web_search_clarification(
            redis,
            private=private,
            chat_id=chat_id,
            user_id=user_id,
        )
        return None
    return clarification


async def clear_web_search_clarification(
    redis: object,
    *,
    private: bool,
    chat_id: int,
    user_id: int,
) -> None:
    if not hasattr(redis, "delete"):
        return
    key = web_search_clarification_key(private=private, chat_id=chat_id, user_id=user_id)
    try:
        await redis.delete(key)  # type: ignore[attr-defined]
    except Exception as exc:
        logger.warning(
            "web_search_clarification_unavailable",
            extra={"operation": "delete", "error_type": type(exc).__name__},
        )


def build_followup_intent(
    text: str,
    clarification: WebSearchClarification,
    *,
    bot_username: str | None = None,
) -> WebSearchIntent | None:
    explicit = parse_web_search_intent(text, bot_username=bot_username)
    if explicit is not None:
        return explicit
    stripped = " ".join(text.split()).strip(" :—-")
    if not stripped or stripped.startswith("/"):
        return None
    if clarification.intent_type == "weather":
        return WebSearchIntent(query=f"погода {stripped} сегодня", intent_type="weather")
    if clarification.intent_type == "general":
        topic = clarification.original_query.strip()
        if topic.casefold() in {"новости", "последние", "актуально"}:
            return WebSearchIntent(query=f"новости {stripped}", intent_type="general")
        if topic.casefold() == "курс":
            return WebSearchIntent(query=f"курс {stripped}", intent_type="general")
    return None


def _decode_clarification(raw: Any) -> WebSearchClarification | None:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        data = json.loads(str(raw))
    except json.JSONDecodeError:
        return None
    if data.get("kind") != CLARIFICATION_KIND:
        return None
    intent_type = str(data.get("intent_type") or "")
    if intent_type not in {"weather", "general"}:
        return None
    return WebSearchClarification(
        intent_type=intent_type,
        original_query=str(data.get("original_query") or "")[:120],
        created_at=float(data.get("created_at") or 0),
    )


def _safe_store_query(query: str) -> str:
    clipped = " ".join(query.split())[:120]
    if SECRET_LIKE_RE.search(clipped):
        return "<masked>"
    return clipped
