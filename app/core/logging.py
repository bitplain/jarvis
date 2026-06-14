import logging
import re
from collections.abc import Mapping
from typing import Any

from pythonjsonlogger import json as jsonlogger

SECRET_PATTERNS = [
    re.compile(r"(\b(?:token|api[_-]?key|authorization|password|secret)\b=)[^,\s]+", re.I),
    re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]+", re.I),
]


def redact(value: object) -> object:
    if isinstance(value, str):
        redacted = value
        for pattern in SECRET_PATTERNS:
            redacted = pattern.sub(r"\1<redacted>", redacted)
        return redacted
    if isinstance(value, Mapping):
        safe: dict[object, object] = {}
        for key, item in value.items():
            if re.search(r"token|api[_-]?key|authorization|password|secret", str(key), re.I):
                safe[key] = "<redacted>"
            else:
                safe[key] = redact(item)
        return safe
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.msg)
        if record.args:
            record.args = tuple(redact(arg) for arg in record.args)
        return True


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(
        jsonlogger.JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    handler.addFilter(RedactingFilter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())


def safe_extra(**kwargs: Any) -> dict[str, object]:
    return {"extra": redact(kwargs)}
