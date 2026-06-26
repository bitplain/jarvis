# Hotfix Logging Hygiene

## Цель

Убрать ложное ощущение application error для обычных operational logs и закрыть риск утечки Telegram bot token через Telegram Bot API URL в HTTP client logs.

## Что изменено

- `app/core/logging.py` теперь разделяет app logs: `DEBUG`/`INFO` идут в stdout, `WARNING`/`ERROR`/`exception` остаются в stderr.
- Central redaction filter маскирует Telegram Bot API URLs вида `https://api.telegram.org/bot<TOKEN>/...`, Authorization/Bearer headers, token/key/password/secret fields, nested `extra` values и URL-like objects.
- `httpx`, `httpcore` и `aiohttp` request info logs понижены до `WARNING`, чтобы routine request logs не печатали полный Telegram URL.
- `app/services/telegram_webhook_setup.py` использует общий redactor при sanitizing webhook errors.
- `app/workers/arq_settings.py` подключает logging config через arq `on_startup`, чтобы worker jobs использовали тот же stdout/stderr split и redaction.

## Ограничение

Если arq или Railway runtime пишет ранние сторонние stderr logs до запуска app-controlled `configure_logging`, Railway всё ещё может показать `[err]` без фактической ошибки. Это не считается failure без traceback, failed exit code или failed job marker. App-controlled logs после startup должны быть stdout/stderr-clean.

## Проверки

```bash
uv run --python 3.12 --extra dev pytest -q tests/test_logging_hygiene.py tests/test_webhook_self_healing_startup.py tests/test_smoke_logging_hygiene_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_logging_hygiene_readiness.py
```

Expected verdict:

```text
PASS_LOGGING_HYGIENE_READINESS
PASS_HOTFIX_LOGGING_HYGIENE_READY
```
