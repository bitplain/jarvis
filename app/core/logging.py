import logging
import re
import sys
from collections.abc import Mapping
from typing import Any, cast

from pythonjsonlogger import json as jsonlogger

SECRET_PATTERNS = [
    re.compile(r"(https://api\.telegram\.org/bot)[^/\s]+", re.I),
    re.compile(r"(Authorization\s*:\s*)Bearer\s+[A-Za-z0-9._~+/=-]+", re.I),
    re.compile(r"(\bX-API-Key\s*:\s*)[A-Za-z0-9._~+/=-]+", re.I),
    re.compile(
        r"(\b(?:token|api[_-]?key|authorization|password|secret)\b\s*:\s*)[A-Za-z0-9._~+/=-]+",
        re.I,
    ),
    re.compile(r"(\b(?:token|api[_-]?key|authorization|password|secret)\b=)[^,\s]+", re.I),
    re.compile(r"(^|[^A-Za-z0-9_])\d{5,}:[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]+", re.I),
]
LOG_RECORD_STANDARD_ATTRS = set(logging.makeLogRecord({}).__dict__)


class MaxLevelFilter(logging.Filter):
    def __init__(self, max_level: int) -> None:
        super().__init__()
        self.max_level = max_level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno <= self.max_level


def redact_secrets(value: str) -> str:
    redacted = value
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub(r"\1<redacted>", redacted)
    return redacted


def redact(value: object) -> object:
    if isinstance(value, str):
        return redact_secrets(value)
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
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    if isinstance(value, set):
        return {redact(item) for item in value}
    rendered = str(value)
    redacted_rendered = redact(rendered)
    if redacted_rendered != rendered:
        return redacted_rendered
    return value


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.msg)
        if record.args:
            if isinstance(record.args, Mapping):
                record.args = cast(Mapping[str, object], redact(record.args))
            else:
                record.args = tuple(redact(arg) for arg in record.args)
        for key, value in list(record.__dict__.items()):
            if key not in LOG_RECORD_STANDARD_ATTRS:
                record.__dict__[key] = redact(value)
        return True


class RedactingFormatter(jsonlogger.JsonFormatter):
    def format(self, record: logging.LogRecord) -> str:
        rendered = super().format(record)
        return redact_secrets(rendered)

    def formatException(self, ei: Any) -> str:
        rendered = super().formatException(ei)
        if isinstance(rendered, list):
            rendered = "\n".join(rendered)
        return redact_secrets(rendered)


def configure_logging(level: str) -> None:
    formatter = RedactingFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    redacting_filter = RedactingFilter()
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(formatter)
    stdout_handler.addFilter(redacting_filter)
    stdout_handler.addFilter(MaxLevelFilter(logging.INFO))
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.WARNING)
    stderr_handler.setFormatter(formatter)
    stderr_handler.addFilter(redacting_filter)
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(stdout_handler)
    root.addHandler(stderr_handler)
    root.setLevel(level.upper())
    for logger_name in ("httpx", "httpcore", "aiohttp"):
        logging.getLogger(logger_name).setLevel(logging.WARNING)


def safe_extra(**kwargs: Any) -> dict[str, object]:
    return {"extra": redact(kwargs)}
