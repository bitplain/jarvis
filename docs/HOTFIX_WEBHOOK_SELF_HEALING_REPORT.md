# Hotfix Webhook self-healing report

Verdict: `PASS_WEBHOOK_SELF_HEALING_READY`

## Симптом

После merge PR #7 бот ожил только после ручного запуска:

```bash
PYTHONPATH=/app APP_ENV=production python scripts/setup_telegram_webhook.py
```

До ручного setup API и worker были живы, но Telegram updates не доходили до приложения.

## Root cause

PR #7 защитил production от будущего `deleteWebhook`, но не восстанавливал уже удалённый Telegram webhook автоматически.
Webhook state хранится на стороне Telegram, поэтому обычный merge/deploy не меняет удалённое состояние Telegram webhook.

## Fix

- `jarvis-api` при `APP_ENV=production` на startup после migrations запускает Telegram webhook self-healing setup.
- Self-healing использует общий sanitized setup code с ручным `scripts/setup_telegram_webhook.py` / `scripts/set_telegram_webhook.py`.
- Worker не импортирует и не запускает webhook setup.
- Dev/test startup не вызывает Telegram webhook setup.
- Отсутствующие `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, `PUBLIC_BASE_URL` или временная ошибка Telegram API не валят API startup.
- Логи содержат только sanitized события `telegram_webhook_setup_started`, `telegram_webhook_setup_completed`, `telegram_webhook_setup_failed`, `webhook_host`, `webhook_path`.
- Production guard от `deleteWebhook` в polling readiness/runner сохранён.

## Tests

- `test_production_api_startup_runs_webhook_setup_after_migrations`
- `test_non_production_startup_does_not_run_webhook_setup`
- `test_missing_webhook_token_does_not_fail_production_startup`
- `test_webhook_setup_failure_does_not_fail_production_startup`
- `test_webhook_setup_logs_do_not_contain_token`
- `test_worker_startup_does_not_import_webhook_setup`
- `test_webhook_self_healing_readiness_checks_startup_tests_and_docs`

## Smoke

```bash
uv run --python 3.12 --extra dev python scripts/smoke_webhook_self_healing_readiness.py
```

Expected verdict:

```text
PASS_WEBHOOK_SELF_HEALING_READINESS
```

## Что проверить после merge

- В `jarvis-api` startup logs есть `telegram_webhook_setup_started`.
- Если env заполнен, есть `telegram_webhook_setup_completed` с sanitized `webhook_host` и `webhook_path`.
- Если env временно не заполнен или Telegram API недоступен, API всё равно стартует, а ошибка остаётся sanitized.
- Private сообщение `тест` снова даёт ответ.
- Railway HTTP Logs показывает `POST /telegram/webhook`.
- Worker logs показывает один `process_llm_message`.
- Group unauthorized остаётся silent.
- Group authorized mention/reply отвечает один раз.
