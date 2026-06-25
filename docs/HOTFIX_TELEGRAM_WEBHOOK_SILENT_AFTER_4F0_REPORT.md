# Hotfix Telegram Webhook Silent After 4F-0 Report

Verdict: `PASS_HOTFIX_TELEGRAM_WEBHOOK_INGRESS_READY`

## Symptom

После merge PR #6 / Stage 4F-0 бот замолчал:

- private сообщение `тест` не давало ответа;
- group mention/reply тоже не давал ответа;
- `jarvis-api` был жив, startup migrations completed, `/ready` возвращал `200 OK`;
- `jarvis-worker` был жив, worker started, Redis connected;
- после сообщения боту в Railway HTTP Logs не было `POST /telegram/webhook`;
- в worker logs не было `process_llm_message`.

## Observed

- Локальный route map через synthetic tests подтверждает `POST /telegram/webhook`, `GET /health`, `GET /ready`.
- Synthetic private admin update проходит через FastAPI webhook route и создаёт ровно один `process_llm_message(private=true)`.
- Synthetic private unauthorized update проходит через route, отвечает `Доступ запрещён.` и не создаёт job.
- Synthetic group admin mention проходит через route и создаёт ровно один `process_llm_message(private=false)`.
- Synthetic group unauthorized update проходит через route, молчит и не создаёт job.
- PR #6 не менял FastAPI webhook route, `app.include_router(routes_telegram.router)`, webhook setup URL или Redis enqueue path.

## Root cause

Code-level ingress не был сломан PR #6. Конкретная причина production silence - destructive readiness path:

- `scripts/smoke_streaming_readiness.py` вызывает polling readiness.
- `scripts/smoke_group_readiness.py` тоже может вызывать polling readiness.
- `scripts/smoke_polling_readiness.py` без проверки `APP_ENV=production` выполнял `bot.delete_webhook(drop_pending_updates=False)`.
- Если readiness запускался в Railway/production env после deploy, Telegram webhook удалялся. После этого Telegram больше не отправлял HTTP `POST /telegram/webhook`, поэтому API/worker оставались healthy, но входящих updates и worker jobs не было.

## Fix

- `scripts/smoke_polling_readiness.py` при `APP_ENV=production` возвращает blocked readiness и не вызывает `deleteWebhook`/`getMe`.
- `scripts/run_polling.py` отказывается запускаться при `APP_ENV=production` до любого `deleteWebhook`.
- Добавлены synthetic webhook ingress tests без live Telegram calls.
- Добавлен `scripts/smoke_telegram_webhook_ingress_readiness.py`.
- Документация обновлена: polling smoke локальный, production webhook не должен удаляться readiness scripts.

## Tests

- `tests/test_telegram_webhook_ingress.py`
- `test_polling_readiness_does_not_delete_webhook_in_production`
- `test_polling_runner_refuses_production_webhook_runtime`
- `tests/test_smoke_telegram_webhook_ingress_readiness.py`

## Что проверить после merge

- В Railway выполнить approved webhook setup script, если production webhook уже удалён: `PYTHONPATH=/app python scripts/setup_telegram_webhook.py`.
- Private `тест` даёт ответ.
- Railway HTTP Logs показывает `POST /telegram/webhook`.
- Worker logs показывает один `process_llm_message`.
- Group unauthorized остаётся silent.
- Group authorized mention/reply отвечает один раз.

## Проверки

```bash
uv run --python 3.12 --extra dev ruff check .
uv run --python 3.12 --extra dev mypy app
uv run --python 3.12 --extra dev pytest -q
uv run --python 3.12 --extra dev python scripts/smoke_telegram_webhook_ingress_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_group_stability_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_railway_readiness.py
```
