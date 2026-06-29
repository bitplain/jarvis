from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from html import escape
from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.services.telegram_formatting import TELEGRAM_HTML_LIMIT

ALLOWED_EVENT_ACTION_IDS = {"done", "snooze", "details"}
EVENT_CALLBACK_PREFIX = "event"
_EVENT_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_ACTION_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,16}$")
_ELLIPSIS = "…"
_BOLD_OPEN = "<b>"
_BOLD_CLOSE = "</b>"


@dataclass(frozen=True)
class StructuredCardFact:
    label: str
    value: str


@dataclass(frozen=True)
class StructuredCardAction:
    id: str
    label: str


@dataclass(frozen=True)
class StructuredCard:
    type: str
    title: str
    severity: str
    facts: list[StructuredCardFact]
    summary: str
    actions: list[StructuredCardAction]


def render_card_to_telegram_text(
    card_json: Mapping[str, Any] | None,
    *,
    fallback_title: str = "Событие",
    fallback_body: str | None = None,
) -> str:
    card = parse_structured_card(card_json)
    if card is None:
        return _render_fallback_card(
            fallback_title or "Событие",
            fallback_body or "Карточка события временно недоступна.",
        )

    builder = _TelegramHtmlBuilder(TELEGRAM_HTML_LIMIT)
    if not builder.add_text(card.title, bold=True):
        return builder.render()
    if card.facts:
        if not builder.add_separator("\n\n"):
            return builder.render()
        for index, fact in enumerate(card.facts):
            if not builder.add_text(fact.label):
                return builder.render()
            if not builder.add_separator(": "):
                return builder.render()
            if not builder.add_text(fact.value, bold=True):
                return builder.render()
            if index < len(card.facts) - 1 and not builder.add_separator("\n"):
                return builder.render()
    if card.summary:
        if not builder.add_separator("\n\n"):
            return builder.render()
        builder.add_text(card.summary)
    return builder.render()


def render_card_buttons(
    event_id: str,
    card_json: Mapping[str, Any] | None,
) -> InlineKeyboardMarkup | None:
    card = parse_structured_card(card_json)
    if card is None or not card.actions:
        return None
    rows: list[list[InlineKeyboardButton]] = []
    for action in card.actions:
        try:
            callback_data = build_event_callback_data(action.id, event_id)
        except ValueError:
            continue
        label = _button_label(action.label)
        if not label:
            continue
        rows.append([InlineKeyboardButton(text=label, callback_data=callback_data)])
    if not rows:
        return None
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_event_callback_data(action_id: str, event_id: str) -> str:
    action = action_id.strip().lower()
    normalized_event_id = event_id.strip().lower().replace("-", "")
    if action not in ALLOWED_EVENT_ACTION_IDS or not _ACTION_ID_RE.fullmatch(action):
        raise ValueError("invalid_event_action")
    if not _EVENT_ID_RE.fullmatch(normalized_event_id):
        raise ValueError("invalid_event_id")
    callback_data = f"{EVENT_CALLBACK_PREFIX}:{action}:{normalized_event_id}"
    if len(callback_data.encode("utf-8")) > 64:
        raise ValueError("event_callback_data_too_long")
    return callback_data


def parse_structured_card(card_json: Mapping[str, Any] | None) -> StructuredCard | None:
    if not isinstance(card_json, Mapping):
        return None
    card_type = _clean_string(card_json.get("type"))
    title = _clean_string(card_json.get("title"))
    severity = _clean_string(card_json.get("severity")) or "info"
    if not card_type or not title:
        return None
    facts = _parse_facts(card_json.get("facts"))
    actions = _parse_actions(card_json.get("actions"))
    summary = _clean_string(card_json.get("summary")) or ""
    return StructuredCard(
        type=card_type,
        title=title,
        severity=severity,
        facts=facts,
        summary=summary,
        actions=actions,
    )


def _parse_facts(value: Any) -> list[StructuredCardFact]:
    if value is None:
        return []
    if not isinstance(value, list):
        return []
    facts: list[StructuredCardFact] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        label = _clean_string(item.get("label"))
        fact_value = _clean_string(item.get("value"))
        if label and fact_value:
            facts.append(StructuredCardFact(label=label, value=fact_value))
    return facts


def _parse_actions(value: Any) -> list[StructuredCardAction]:
    if value is None:
        return []
    if not isinstance(value, list):
        return []
    actions: list[StructuredCardAction] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        action_id = _clean_string(item.get("id"))
        label = _clean_string(item.get("label"))
        if action_id and label:
            actions.append(StructuredCardAction(id=action_id, label=label))
    return actions


def _clean_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.strip().split())
    return cleaned or None


def _escape_text(value: str) -> str:
    return escape(value, quote=True)


def _render_fallback_card(title: str, body: str) -> str:
    builder = _TelegramHtmlBuilder(TELEGRAM_HTML_LIMIT)
    if not builder.add_text(title, bold=True):
        return builder.render()
    if not builder.add_separator("\n\n"):
        return builder.render()
    builder.add_text(body)
    return builder.render()


class _TelegramHtmlBuilder:
    def __init__(self, limit: int) -> None:
        self._remaining = limit
        self._parts: list[str] = []

    def add_separator(self, separator: str) -> bool:
        if len(separator) > self._remaining:
            return False
        self._parts.append(separator)
        self._remaining -= len(separator)
        return True

    def add_text(self, value: str, *, bold: bool = False) -> bool:
        if not value:
            return True
        prefix = _BOLD_OPEN if bold else ""
        suffix = _BOLD_CLOSE if bold else ""
        overhead = len(prefix) + len(suffix)
        if self._remaining <= overhead:
            return False
        budget = self._remaining - overhead
        escaped = _escape_text(value)
        completed = len(escaped) <= budget
        rendered_text = escaped if completed else _escape_text_to_budget(value, budget)
        self._parts.append(f"{prefix}{rendered_text}{suffix}")
        self._remaining -= overhead + len(rendered_text)
        return completed

    def render(self) -> str:
        return "".join(self._parts)


def _escape_text_to_budget(value: str, budget: int) -> str:
    if budget <= 0:
        return ""
    escaped = _escape_text(value)
    if len(escaped) <= budget:
        return escaped
    if budget <= len(_ELLIPSIS):
        return _ELLIPSIS[:budget]
    escaped_budget = budget - len(_ELLIPSIS)
    low = 0
    high = len(value)
    while low < high:
        midpoint = (low + high + 1) // 2
        if len(_escape_text(value[:midpoint])) <= escaped_budget:
            low = midpoint
        else:
            high = midpoint - 1
    return f"{_escape_text(value[:low])}{_ELLIPSIS}"


def _button_label(value: str) -> str:
    return " ".join(value.strip().split())[:64]
