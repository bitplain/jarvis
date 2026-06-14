# Stage 1R Live Telegram Smoke Report

## Стартовые commits

- Stage 1: `870f443 Stage 1: bootstrap Jarvis Telegram AI bot`
- Stage 1R-ENV: `305bf0a Stage 1R: bootstrap real environment`
- Stage 1R-ID: `d07051c Stage 1R: resolve admin id and OpenRouter smoke`

GitHub repo не создавался. Push не выполнялся. `.env` не коммитился.

## ADMIN_TELEGRAM_IDS

Команды:

```bash
uv run --python 3.12 --extra dev python scripts/bootstrap_real_env.py --apply --delete-webhook-for-getupdates
uv run --python 3.12 --extra dev python scripts/bootstrap_real_env.py --dry-run
```

Результат:

- `deleteWebhook`: `ok`, `drop_pending_updates=False`.
- `ADMIN_TELEGRAM_IDS`: `<set>`.
- Numeric id в отчёт не выводился.
- Env readiness: `PASS_STAGE_1R_ENV_READY`.

## Docker runtime

Команды:

```bash
docker compose down --remove-orphans
docker compose build
docker compose up -d
docker compose ps
docker compose exec api alembic upgrade head
docker compose exec api pytest -q
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8000/ready
```

Результат:

- `docker compose build` — PASS.
- `docker compose up -d` — PASS.
- `docker compose ps` — `api`, `postgres`, `redis` healthy; `worker` running.
- `docker compose exec api alembic upgrade head` — PASS.
- `docker compose exec api pytest -q` — PASS, `20 passed`.
- `/health` — `{"status":"ok"}`.
- `/ready` — `{"status":"ok","checks":{"postgres":true,"redis":true}}`.

## Tunnel

Проверки:

```bash
command -v cloudflared || true
command -v ngrok || true
```

Результат:

- `cloudflared`: `<missing>`.
- `ngrok`: `<missing>`.
- Временный HTTPS tunnel не поднят.
- `PUBLIC_BASE_URL`: `<not_public_https>`.

Инструкция создана: `docs/STAGE_1R_TUNNEL_SETUP.md`.

## Webhook

- Telegram webhook ранее был удалён для polling.
- Webhook не восстановлен, потому что нет публичного HTTPS tunnel URL.
- `scripts/set_telegram_webhook.py` не создавался: Stage 1R-LIVE остановлен до шага установки webhook.

## LLM smoke

- Yandex smoke до Stage 1R-LIVE: `chat_smoke_ok`.
- OpenRouter smoke до Stage 1R-LIVE: `OPENROUTER_READY`.
- `scripts/smoke_llm.py` не запускался и не создавался, потому что live runtime остановлен на отсутствии public HTTPS tunnel.

## Telegram command smoke

Не выполнялся:

- `/start` — BLOCKED.
- `/help` — BLOCKED.
- `/models` — BLOCKED.
- `/status` — BLOCKED.
- обычный текстовый запрос — BLOCKED.
- `/reset` — BLOCKED.

Причина: Telegram webhook не установлен без публичного HTTPS URL.

## DB persistence и memory reset

Не выполнялись:

- persistence check — BLOCKED.
- reset effect check — BLOCKED.

Причина: live Telegram updates не поступали в локальный API.

## Найденные проблемы

- На локальной машине нет `cloudflared`.
- На локальной машине нет `ngrok`.
- `PUBLIC_BASE_URL` не является публичным HTTPS URL.

## Что исправлено

- `ADMIN_TELEGRAM_IDS` получен и записан в локальный `.env`.
- Создана инструкция по tunnel setup.

## Что осталось сделать

1. Установить или предоставить доступный tunnel tool: `cloudflared` или `ngrok`.
2. Поднять tunnel до `http://localhost:8000`.
3. Записать HTTPS URL в `PUBLIC_BASE_URL` локального `.env`.
4. Пересоздать `api` и `worker`.
5. Установить Telegram webhook.
6. Выполнить live Telegram command smoke и DB checks.

## Verdict

`BLOCKED_NEEDS_PUBLIC_HTTPS_TUNNEL`
