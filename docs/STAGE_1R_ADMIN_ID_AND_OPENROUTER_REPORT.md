# Stage 1R-ID Admin ID and OpenRouter Report

## Стартовые commits

- Stage 1: `870f443 Stage 1: bootstrap Jarvis Telegram AI bot`
- Stage 1R-ENV: `305bf0a Stage 1R: bootstrap real environment`

GitHub repo не создавался. Push не выполнялся. `.env` не коммитился.

## ADMIN_TELEGRAM_IDS

Команда:

```bash
uv run --python 3.12 --extra dev python scripts/bootstrap_real_env.py --apply --delete-webhook-for-getupdates
```

Результат:

- Telegram webhook был временно удалён: `telegram deleteWebhook: ok`.
- `drop_pending_updates=False`.
- `ADMIN_TELEGRAM_IDS`: `<missing>`.
- `getUpdates` вернул пустой список личных сообщений.

Итог: нужен ручной `/start` боту в личке, затем повторный запуск bootstrap.

## Webhook restore

- `PUBLIC_BASE_URL`: `<not_public_https>`.
- Webhook не восстановлен, потому что Telegram webhook требует публичный HTTPS URL.

## OpenRouter

Официальная форма OpenRouter chat completion подтверждена по документации:

- endpoint: `POST /api/v1/chat/completions`
- auth: `Authorization: Bearer <token>`
- тело: `model`, `messages`, `max_tokens`

Источники:

- `https://openrouter.ai/docs/api/api-reference/chat/send-chat-completion-request`
- `https://openrouter.ai/docs/api/reference/authentication`
- `https://openrouter.ai/docs/api/api-reference/models/get-models`

Диагностика:

- `/api/v1/models`: `http_200`.
- Текущая старая модель: sanitized `http_400`.
- Причина: provider route вернул sanitized ошибку про минимальное значение output tokens.
- Следующая candidate model прошла real chat smoke.
- Итоговый provider status: `OPENROUTER_READY`.

Выбранная OpenRouter model записана в локальный `.env`, но значение в отчёте не раскрывается.

## Yandex

- Yandex real chat smoke: `chat_smoke_ok`.

## Docker и API smoke

После Stage 1R-ID полного runtime smoke не выполнялся, потому что `ADMIN_TELEGRAM_IDS` всё ещё `<missing>`.

Последние базовые проверки после Stage 1R-ENV:

- `docker compose build` — PASS.
- `docker compose up -d` — PASS.
- `docker compose ps` — `api`, `postgres`, `redis` healthy; `worker` running.
- `docker compose exec api alembic upgrade head` — PASS.
- `docker compose exec api pytest -q` — PASS, `18 passed`.
- `curl /health` — `{"status":"ok"}`.
- `curl /ready` — `{"status":"ok","checks":{"postgres":true,"redis":true}}`.

## Telegram live smoke

Не выполнялся:

- `ADMIN_TELEGRAM_IDS` не заполнен.
- Webhook не восстановлен из-за отсутствия public HTTPS URL.

## Выполненные команды

```bash
git status --short
uv run --python 3.12 --extra dev python scripts/bootstrap_real_env.py --apply --delete-webhook-for-getupdates
uv run --python 3.12 --extra dev python scripts/bootstrap_real_env.py --dry-run
uv run --python 3.12 --extra dev pytest -q tests/test_bootstrap_real_env.py
```

## Что исправлено

- OpenRouter candidate order приведён к Stage 1R-ID требованиям.
- Если текущая `OPENROUTER_MODEL` возвращает sanitized `http_400`, bootstrap пробует следующую доступную candidate model.
- Первый успешный OpenRouter smoke записывает новую `OPENROUTER_MODEL` в локальный `.env`.
- OpenRouter ошибки теперь содержат sanitized HTTP status, request id, provider name, короткое сообщение и безопасный fragment provider raw error.
- `deleteWebhook` сохраняет pending updates по умолчанию.
- Добавлен явный флаг `--drop-pending-updates`.

## Что осталось сделать руками

1. Открыть Telegram.
2. Найти своего бота.
3. Отправить ему `/start` в личке.
4. Запустить:

```bash
uv run --python 3.12 --extra dev python scripts/bootstrap_real_env.py --apply --delete-webhook-for-getupdates
uv run --python 3.12 --extra dev python scripts/bootstrap_real_env.py --dry-run
```

5. Настроить `PUBLIC_BASE_URL` на публичный HTTPS URL и восстановить webhook перед Telegram live smoke.

## Stage 1R-LIVE update

- `ADMIN_TELEGRAM_IDS`: `<set>` после ручного `/start` и повторного bootstrap.
- `cloudflared`: установлен, но quick tunnel в этой сети отдавал `530`.
- `ngrok`: Homebrew download упал на TLS error.
- `localtunnel`: поднят и дал публичный HTTPS URL.
- Webhook установлен.
- Synthetic webhook smoke через публичный URL прошёл, DB persistence/reset подтверждены.
- Полный real user-originated Telegram smoke всё ещё требует сообщения из пользовательского Telegram-клиента.

Детальный отчёт: `docs/STAGE_1R_LIVE_TELEGRAM_SMOKE_REPORT.md`.

## Verdict

Original Stage 1R-ID verdict был `BLOCKED_NEEDS_MANUAL_TELEGRAM_START`.

После Stage 1R-LIVE bootstrap этот блокер снят: `ADMIN_TELEGRAM_IDS=<set>`.

Текущий блокер: `BLOCKED_NEEDS_MANUAL_TELEGRAM_MESSAGE`.
