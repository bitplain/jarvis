# Hotfix Redact Exception Tracebacks

## Симптом

После PR #23 logging hygiene redaction применялся к `record.msg`, `record.args` и structured `extra`, но audit показал P0 blocker: если secret-bearing Telegram URL или Authorization header попадал в текст исключения, `logger.exception(...)` мог вывести эти данные в formatted traceback.

## Root cause

`logging.Formatter` формирует exception text из `record.exc_info` после работы logging filter. Обычный `JsonFormatter` добавлял traceback в итоговую log string без повторного redaction, поэтому sanitize на уровне `record.msg`/`args` не покрывал `formatException`.

## Fix

- В `app/core/logging.py` добавлен центральный `redact_secrets(value: str) -> str`.
- `redact(...)` продолжает очищать structured values, mappings, tuples, lists и sets.
- Новый `RedactingFormatter` наследует `pythonjsonlogger.JsonFormatter` и применяет `redact_secrets(...)` к `format(...)` и `formatException(...)`.
- `configure_logging(...)` использует `RedactingFormatter` для stdout и stderr handlers.
- `RedactingFilter` остаётся на месте для ранней очистки `record.msg`, `record.args` и nested `extra`.

## Что остаётся видно в логах

В exception logs остаются:

- событие, например `telegram setup failed`;
- `Traceback (most recent call last)`;
- exception type, например `RuntimeError`;
- безопасный non-secret context.

Маскируются:

- Telegram Bot API URLs вида `https://api.telegram.org/bot<TOKEN>/...`;
- raw Telegram token-like fragments;
- `Authorization: Bearer ...` и standalone `Bearer ...`;
- `X-API-Key`, `api_key=`, `token=`, password/secret-like fields.

## Verification

```bash
uv run --python 3.12 --extra dev pytest -q tests/test_logging_hygiene.py
uv run --python 3.12 --extra dev python scripts/smoke_logging_hygiene_readiness.py
```

Expected verdict:

```text
PASS_LOGGING_HYGIENE_READINESS
PASS_HOTFIX_REDACT_EXCEPTION_TRACEBACKS_READY
```
