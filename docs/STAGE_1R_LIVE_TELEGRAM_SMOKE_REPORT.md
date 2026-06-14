# Stage 1R Live Telegram Smoke Report

## Стартовые commits

- Stage 1: `870f443 Stage 1: bootstrap Jarvis Telegram AI bot`
- Stage 1R-ENV: `305bf0a Stage 1R: bootstrap real environment`
- Stage 1R-ID: `d07051c Stage 1R: resolve admin id and OpenRouter smoke`

GitHub repo не создавался. Push не выполнялся. `.env` не коммитился.

## ADMIN_TELEGRAM_IDS

- `deleteWebhook`: `ok`, `drop_pending_updates=False`.
- `ADMIN_TELEGRAM_IDS`: `<set>`.
- Numeric id в отчёт не выводился.
- Env readiness: `PASS_STAGE_1R_ENV_READY`.

## Tunnel

- `cloudflared` установлен через Homebrew.
- Cloudflare quick tunnel поднимался, но отдавал `530 The origin has been unregistered from Argo Tunnel`.
- `ngrok` через Homebrew не установился из-за TLS download error с `bin.ngrok.com`.
- `localtunnel` поднят через `npx --yes localtunnel --port 8000`.
- `PUBLIC_BASE_URL`: `<set: public_https>`.
- Внешний `/health` через tunnel: `200 OK`.

## Webhook

- Добавлен `scripts/set_telegram_webhook.py`.
- `setWebhook`: `ok`.
- `getWebhookInfo`: `ok`.
- `pending_update_count`: `0`.
- `last_error`: stale `Read timeout expired`.
- Webhook URL в отчёте указан только как sanitized host/path.

## LLM smoke

- Добавлен `scripts/smoke_llm.py`.
- Yandex: `OK`.
- OpenRouter: `OK`.
- Forced fallback: `OK`.
- Verdict: `PASS_LLM_SMOKE`.

## Telegram webhook smoke

Проверено через публичный HTTPS tunnel и `X-Telegram-Bot-Api-Secret-Token` synthetic updates:

- `/start` — `http_200`.
- `/help` — `http_200`.
- `/models` — `http_200`.
- `/status` — `http_200`.
- обычный текстовый запрос — `http_200`.
- `/reset` — `http_200`.

Это подтверждает локальный webhook endpoint, aiogram routing, outbound Bot API replies, Redis worker enqueue, LLM worker, PostgreSQL persistence и reset path. Это не является полным доказательством user-originated Telegram delivery, потому что бот не может сам отправить сообщение от имени пользователя.

## DB persistence и memory reset

- `count_after_initial_reset`: `0`.
- После обычного текстового запроса: `USER:1`, `ASSISTANT:1`.
- `count_after_final_reset`: `0`.

Текст приватного сообщения и ответ не выводились в отчёт.

## Найденные ошибки

1. Webhook возвращал `500 Internal Server Error`.
   - Причина: повторный `build_dispatcher()` пытался прикрепить уже attached aiogram routers.
   - Fix: router modules получили `build_router()`, dispatcher теперь включает fresh Router instances.

2. Worker не сохранял assistant message при Telegram flood control на `send_chat_action`.
   - Причина: `TelegramRetryAfter` на typing action валил job.
   - Fix: добавлен `try_send_chat_action()`, typing errors логируются и не блокируют финальный ответ.

3. Cloudflare quick tunnel был нестабилен в этой сети.
   - Fix/обход: использован `localtunnel`.

## Проверки

- `ruff check .` — PASS.
- `mypy app` — PASS.
- `pytest -q` — PASS.
- `docker compose build` — PASS.
- `docker compose up -d` — PASS.
- `docker compose ps` — `api`, `postgres`, `redis` healthy; `worker` running.
- `docker compose exec api alembic upgrade head` — PASS.
- `docker compose exec api pytest -q` — PASS.
- `curl /health` — `{"status":"ok"}`.
- `curl /ready` — `{"status":"ok","checks":{"postgres":true,"redis":true}}`.

## Stage 1R-FINAL-LIVE update

После partial run выполнен настоящий user-originated Telegram live smoke из Telegram-клиента пользователя.

- `/start` — webhook update получен и обработан.
- `/help` — webhook update получен и обработан.
- `/models` — webhook update получен и обработан.
- `/status` — webhook update получен и обработан.
- Обычное текстовое сообщение — webhook update получен, worker LLM job завершён успешно.
- `/reset` — webhook update получен и обработан.
- DB до reset: `USER:1`, `ASSISTANT:1`.
- DB после reset: `0`.

Детальный отчёт: `docs/STAGE_1R_FINAL_LIVE_TELEGRAM_REPORT.md`.

## Verdict

`PASS_STAGE_1R_REAL_RUNTIME_READY`
