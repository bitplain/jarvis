# Stage 3A Business Mode Foundation Report

## Что реализовано

- Обработка Telegram updates: `business_connection`, `business_message`, `edited_business_message`, `deleted_business_messages`.
- Хранение business connections и business messages в PostgreSQL.
- Проверки `business_connection_id`, `is_enabled`, `can_reply`, `BUSINESS_ADMIN_ONLY`, owner из `ADMIN_TELEGRAM_IDS`, allowlist connection/chat.
- Guarded reply mode только при `BUSINESS_MODE_ENABLED=true`, `BUSINESS_REPLY_ENABLED=true` и trigger `BUSINESS_REPLY_TRIGGER`.
- Ответ через typed aiogram `sendMessage` с `business_connection_id`.
- Отдельная business-memory по `business_connection_id + chat_id`.
- `/status` показывает только флаги и агрегированные counts, без полных ids.
- `scripts/smoke_business_readiness.py` проверяет readiness без `getUpdates`.

## Env

Добавлены defaults в `.env.example`:

```env
BUSINESS_MODE_ENABLED=false
BUSINESS_ADMIN_ONLY=true
BUSINESS_REPLY_ENABLED=false
BUSINESS_REPLY_TRIGGER=!jarvis
BUSINESS_MEMORY_MAX_MESSAGES=10
BUSINESS_ALLOWED_CONNECTION_IDS=
BUSINESS_ALLOWED_CHAT_IDS=
```

Реальные значения `.env` не коммитились.

## Миграции и таблицы

Добавлена миграция `20260614_0003_business_mode`.

Новые таблицы:

- `business_connections`
- `business_messages`

Старый `business_connections_stub` оставлен для совместимости исторических Stage 1/2 stub-событий.

## Тесты

Добавлены:

- `tests/test_business_service.py`
- `tests/test_business_router.py`
- `tests/test_business_models.py`
- `tests/test_smoke_business_readiness.py`
- `tests/test_status_command.py`

Покрыто:

- сохранение enabled/disabled/ignored connection;
- отказ owner не из `ADMIN_TELEGRAM_IDS`;
- запрет ответа при `can_reply=false`;
- запрет ответа при `BUSINESS_MODE_ENABLED=false`;
- запрет ответа при `BUSINESS_REPLY_ENABLED=false`;
- отсутствие ответа без trigger;
- LLM и `sendMessage` только с trigger;
- edited/deleted audit без автоответа;
- отдельная business-memory;
- sanitized logs/status/readiness без секретов и полных ids.

## Ручная проверка

Настоящий Telegram Business smoke требует ручного подключения бота к Telegram Business account.
Инструкция: `docs/STAGE_3A_BUSINESS_MODE_REAL_SMOKE.md`.

## Автоматические проверки

Выполнено:

```bash
uv run --python 3.12 --extra dev ruff check .
uv run --python 3.12 --extra dev mypy app
uv run --python 3.12 --extra dev pytest -q
docker compose build
docker compose up -d
docker compose ps
docker compose logs --tail=100 api
docker compose logs --tail=100 worker
docker compose exec api alembic upgrade head
docker compose exec api pytest -q
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8000/ready
uv run --python 3.12 --extra dev python scripts/smoke_llm.py
uv run --python 3.12 --extra dev python scripts/smoke_polling_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_business_readiness.py
BUSINESS_MODE_ENABLED=true BUSINESS_REPLY_ENABLED=true uv run --python 3.12 --extra dev python scripts/smoke_business_readiness.py
git status --short
```

Результаты:

- `ruff check .` — PASS.
- `mypy app` — PASS, `48 source files`.
- local `pytest -q` — PASS, `67 passed`.
- `docker compose build` — PASS.
- `docker compose up -d` — PASS.
- `docker compose ps` — `api`, `postgres`, `redis` healthy; `worker` running.
- API logs — Uvicorn started без ошибок.
- Worker logs — arq worker started с `process_llm_message`.
- `docker compose exec api alembic upgrade head` — PASS, upgrade `20260614_0002 -> 20260614_0003`.
- container `pytest -q` — PASS, `67 passed`.
- `/health` — `{"status":"ok"}`.
- `/ready` — `{"status":"ok","checks":{"postgres":true,"redis":true}}`.
- `scripts/smoke_llm.py` — `PASS_LLM_SMOKE`.
- `scripts/smoke_polling_readiness.py` — `PASS_POLLING_READINESS`.
- `scripts/smoke_business_readiness.py` на default-off env — `BLOCKED_BUSINESS_READINESS`, потому что `BUSINESS_MODE_ENABLED=false` и `BUSINESS_REPLY_ENABLED=false`.
- `scripts/smoke_business_readiness.py` с временными `BUSINESS_MODE_ENABLED=true BUSINESS_REPLY_ENABLED=true` — `PASS_BUSINESS_READINESS`.
- `git status --short` — только ожидаемые Stage 3A изменения, `.env` не изменён.

Если ручной smoke не выполнен, финальный verdict остаётся:

`BLOCKED_NEEDS_MANUAL_BUSINESS_MODE_TEST`
