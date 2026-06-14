# Stage 1 Report

## Что создано

- Production-ready каркас Telegram AI bot Jarvis на FastAPI, aiogram 3.x, PostgreSQL, Redis и arq.
- Webhook/API endpoints: `GET /health`, `GET /ready`, `POST /telegram/webhook`, `GET /admin/models`.
- LLM abstraction и провайдеры Yandex AI Studio OpenAI-compatible API, OpenRouter, fallback Yandex -> OpenRouter.
- Память диалогов в PostgreSQL и ограничение последних `MEMORY_MAX_MESSAGES`.
- Private streaming слой с `sendMessageDraft` adapter и fallback через `sendChatAction`.
- Group handling rules: ответ только на mention или reply на сообщение бота.
- Stage 2/3 stubs для Guest Mode и Secretary / Business Mode.
- Mini App placeholder.
- Docker Compose, Alembic, GitHub Actions, `.env.example`, `.gitignore`, `.dockerignore`.

## Основные файлы

- `app/main.py`, `app/api/*` — FastAPI приложение и routes.
- `app/bot/*` — aiogram Dispatcher, middleware, routers, streaming sinks.
- `app/db/*`, `alembic/*` — SQLAlchemy async модели и initial migration.
- `app/llm/*` — LLM contracts, providers, fallback, model discovery.
- `app/workers/*` — arq worker и LLM job.
- `tests/*` — unit/smoke tests Stage 1.
- `docs/*`, `README.md`, `AGENTS.md` — русская документация и правила проекта.

## Выполненные команды

```bash
uv run --python 3.12 --extra dev ruff check .
uv run --python 3.12 --extra dev mypy app
uv run --python 3.12 --extra dev pytest -q
cp .env.example .env
docker compose build
docker compose up -d
docker compose ps
docker compose logs --tail=100 api
docker compose logs --tail=100 worker
docker compose exec api alembic upgrade head
docker compose exec api pytest -q
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8000/ready
git status --short
```

## Результаты

- `ruff check .` — PASS.
- `mypy app` — PASS, `47 source files`.
- `pytest -q` — PASS, `16 passed`.
- `docker compose build` — PASS.
- `docker compose up -d` — PASS.
- `docker compose ps` — `api`, `worker`, `postgres`, `redis` запущены; `api`, `postgres`, `redis` healthy.
- `docker compose logs --tail=100 api` — Uvicorn стартовал без ошибок.
- `docker compose logs --tail=100 worker` — arq worker стартовал с `process_llm_message`.
- `docker compose exec api alembic upgrade head` — PASS.
- `docker compose exec api pytest -q` — PASS, `16 passed`.
- `curl /health` — `{"status":"ok"}`.
- `curl /ready` — `{"status":"ok","checks":{"postgres":true,"redis":true}}`.

## Как запустить локально

```bash
cp .env.example .env
docker compose build
docker compose up -d
docker compose exec api alembic upgrade head
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8000/ready
```

## Stage 1R env bootstrap

Для подготовки реального локального `.env` без вывода секретов используется `scripts/bootstrap_real_env.py`.

Инструкция: `docs/STAGE_1R_ENV_BOOTSTRAP.md`.

Stage 1R-ID диагностика admin id и OpenRouter smoke: `docs/STAGE_1R_ADMIN_ID_AND_OPENROUTER_REPORT.md`.

Stage 1R-LIVE tunnel/live smoke status: `docs/STAGE_1R_LIVE_TELEGRAM_SMOKE_REPORT.md`.

## Куда вставить секреты

Только в локальный `.env`:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_WEBHOOK_SECRET`
- `ADMIN_API_TOKEN`
- `YANDEX_AI_API_KEY`
- `OPENROUTER_API_KEY`

Model IDs и Telegram IDs также только в `.env`:

- `TELEGRAM_BOT_USERNAME`
- `ADMIN_TELEGRAM_IDS`
- `YANDEX_AI_MODEL`
- `OPENROUTER_MODEL`

## Обязательные env для реальной работы

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

Без этих значений локальный каркас, БД, Redis, tests и health/ready работают, но реальные Telegram/LLM вызовы не выполняются.

## Отложено

- Guest Mode — Stage 2: `answerGuestQuery`, `guest_query_id`, полноценный guest response.
- Secretary / Business Mode — Stage 3: права Business API, `business_connection_id`, ответы через business connection.
- Mini App — отдельный этап.

## Remote AGENTS sync

Stage 1 выполняется до создания сервера/live project paths.

`remote AGENTS sync = N/A until server/live paths exist`

## Verdict

`PASS_STAGE_1_CORE_READY`

Реальные Telegram/Yandex/OpenRouter smoke tests требуют заполненного `.env`; это не блокирует core readiness, но остаётся runtime-шагом после ручной проверки секретов.
