# Jarvis Telegram AI Bot

Jarvis — production-ready каркас Telegram AI bot для Ubuntu Server с Docker Compose.

## Быстрый запуск

```bash
cp .env.example .env
docker compose build
docker compose up -d
docker compose exec api alembic upgrade head
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8000/ready
```

Логи:

```bash
docker compose logs -f api
docker compose logs -f worker
```

Тесты в контейнере:

```bash
docker compose exec api pytest -q
```

## Куда вставлять секреты

Секреты вставляются только в локальный `.env`, который не попадает в git:

- `TELEGRAM_BOT_TOKEN` — token из BotFather.
- `TELEGRAM_WEBHOOK_SECRET` — секрет для Telegram webhook header.
- `ADMIN_API_TOKEN` — Bearer token для `GET /admin/models`.
- `YANDEX_AI_API_KEY` — ключ Yandex AI Studio.
- `OPENROUTER_API_KEY` — ключ OpenRouter.

Не вставляйте секреты в код, README, AGENTS, workflow-файлы или отчёты.

Для безопасной подготовки реального `.env` можно использовать Stage 1R bootstrap:

```bash
uv run --python 3.12 --extra dev python scripts/bootstrap_real_env.py --dry-run
uv run --python 3.12 --extra dev python scripts/bootstrap_real_env.py --apply
```

Если нужно временно перейти с webhook на polling для получения `ADMIN_TELEGRAM_IDS`, используйте явный флаг. Pending updates по умолчанию сохраняются:

```bash
uv run --python 3.12 --extra dev python scripts/bootstrap_real_env.py --apply --delete-webhook-for-getupdates
```

Подробности: `docs/STAGE_1R_ENV_BOOTSTRAP.md`.

Для локального Telegram webhook без сервера нужен публичный HTTPS tunnel до `http://localhost:8000`.
Инструкция: `docs/STAGE_1R_TUNNEL_SETUP.md`.

Webhook и LLM smoke:

```bash
uv run --python 3.12 --extra dev python scripts/set_telegram_webhook.py
uv run --python 3.12 --extra dev python scripts/set_telegram_webhook.py --info
uv run --python 3.12 --extra dev python scripts/smoke_llm.py
```

## Обязательные переменные

Для локального каркаса без реальных Telegram/LLM вызовов достаточно значений из `.env.example`.

Для работы бота нужны:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_BOT_USERNAME`
- `TELEGRAM_WEBHOOK_SECRET`
- `ADMIN_TELEGRAM_IDS`
- `ADMIN_API_TOKEN`
- `YANDEX_AI_BASE_URL`
- `YANDEX_AI_API_KEY`
- `YANDEX_AI_MODEL`
- `OPENROUTER_API_KEY`
- `OPENROUTER_MODEL`

Yandex OpenAI-compatible base URL обычно указывается как:

```env
YANDEX_AI_BASE_URL=https://ai.api.cloud.yandex.net/v1
```

Model IDs не заданы в коде намеренно. Их нужно задавать только через `.env`.

## Endpoints

- `GET /health` — процесс жив.
- `GET /ready` — PostgreSQL и Redis доступны.
- `POST /telegram/webhook` — вход Telegram updates.
- `GET /admin/models` — диагностика моделей Yandex/OpenRouter, требует `Authorization: Bearer ${ADMIN_API_TOKEN}`.

## Отложенные части

- Guest Mode — Stage 2.
- Secretary / Business Mode — Stage 3.
- Mini App — отдельный будущий этап.
