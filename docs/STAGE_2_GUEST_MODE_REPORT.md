# Stage 2 Guest Mode Report

## Что реализовано

- Telegram Guest Mode для update type `guest_message`.
- Ответ только финальным `answerGuestQuery` через typed aiogram method.
- Guest prompt без обычной chat memory: используется только текст guest-вызова и replied message, если Telegram его передал.
- Защита от публичного LLM-доступа: `GUEST_MODE_ENABLED=false` и `GUEST_MODE_ADMIN_ONLY=true` по умолчанию.
- Если caller user id отсутствует или не входит в `ADMIN_TELEGRAM_IDS`, LLM не вызывается.
- Если `guest_query_id` отсутствует, бот не отвечает и сохраняет диагностический `ignored` record.
- Ошибки LLM возвращают безопасный русский ответ без traceback пользователю.

## Изменённые файлы

- Guest runtime: `app/bot/routers/guest.py`, `app/services/guest_service.py`, `app/api/routes_telegram.py`.
- Config/LLM: `app/core/config.py`, `app/llm/base.py`, `app/llm/fallback.py`, `app/llm/openai_compatible.py`.
- БД: `app/db/models.py`, `alembic/versions/20260614_0002_guest_mode.py`.
- Диагностика: `app/bot/routers/commands.py`.
- Тесты: `tests/test_guest_mode.py`, `tests/test_guest_service.py`, обновлены LLM smoke/fallback tests.
- Документация: `AGENTS.md`, `README.md`, `docs/ARCHITECTURE.md`, `docs/STAGE_1_REPORT.md`, `docs/STAGE_2_GUEST_MODE_REAL_SMOKE.md`.

## Миграция

Добавлена миграция `20260614_0002_guest_mode`.
Она расширяет существующую таблицу `guest_messages_stub`, сохраняя `payload` для совместимости.

Новые поля:

- `telegram_update_id`
- `guest_query_id_hash`
- `caller_user_id_hash`
- `caller_chat_id_hash`
- `request_text`
- `replied_text`
- `response_text`
- `provider`
- `model`
- `status`
- `error_code`
- `answered_at`

Полные Telegram identifiers не сохраняются: для identifiers используются SHA-256 hashes.
Секреты не хранятся и не выводятся в отчётах.

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
```

Результаты:

- `ruff check .` — PASS.
- `mypy app` — PASS, `47 source files`.
- local `pytest -q` — PASS, `37 passed`.
- `docker compose build` — PASS.
- `docker compose up -d` — PASS.
- `docker compose ps` — `api`, `postgres`, `redis` healthy; `worker` running.
- API logs — Uvicorn started без ошибок.
- Worker logs — arq worker started с `process_llm_message`.
- `docker compose exec api alembic upgrade head` — PASS, upgrade `20260614_0001 -> 20260614_0002`.
- container `pytest -q` — PASS, `37 passed`.
- `/health` — `{"status":"ok"}`.
- `/ready` — `{"status":"ok","checks":{"postgres":true,"redis":true}}`.
- `scripts/smoke_llm.py` — `PASS_LLM_SMOKE`.

## Что требует ручного Telegram smoke

Настоящий Guest Mode smoke требует ручного вызова через Telegram-клиент и, возможно, включения Guest Mode в BotFather или настройках Telegram.

Инструкция: `docs/STAGE_2_GUEST_MODE_REAL_SMOKE.md`.
Локальный polling-вариант без tunnel: `docs/STAGE_2R_GUEST_MODE_POLLING_SMOKE.md`.

Не засчитывать как Stage 2 real smoke:

- обычное сообщение в личке;
- обычное сообщение в группе, где бот добавлен участником;
- group mention без update type `guest_message`.

## Stage 2R polling path

Webhook/tunnel smoke был заблокирован на tunnel layer:

- localtunnel возвращал `502 Bad Gateway`;
- Cloudflare quick tunnel возвращал `530`;
- локальный API при этом отвечал на `/health` и `/ready`.

Для локального Mac добавлен polling path:

- `scripts/smoke_polling_readiness.py` — удаляет webhook, проверяет `getMe`, Guest Mode env, Postgres, Redis и LLM smoke, но не вызывает `getUpdates`;
- `scripts/run_polling.py` — запускает общий aiogram Dispatcher через polling с `allowed_updates`, включая `guest_message`;
- `.env.polling.example` — host-side overrides без секретов;
- `docker-compose.override.yml` — публикует Postgres `5432` и Redis `6379` для host-side polling runner.

Stage 2R polling readiness на локальном Mac:

- `deleteWebhook` — OK, `drop_pending_updates=false`;
- Telegram `getMe` — OK;
- Guest Mode env — enabled/admin-only;
- Postgres — OK;
- Redis — OK;
- LLM smoke — `PASS_LLM_SMOKE`;
- verdict — `PASS_POLLING_READINESS`.

Stage 2R real polling smoke:

- отчёт: `docs/STAGE_2R_GUEST_MODE_REAL_POLLING_REPORT.md`;
- polling получил настоящие guest records через `guest_message` path;
- свежие DB records: `3`;
- `status=answered`: `3`;
- `error_code` пустой: `3`;
- ответы получены пользователем в Telegram;
- verdict — `PASS_STAGE_2_GUEST_MODE_REAL_READY`.

## Remote AGENTS sync

В репозитории есть только локальный `AGENTS.md`.
Серверные/live project paths не заведены.

`remote AGENTS sync = N/A until server/live paths exist`

## Verdict

Код, миграция, synthetic/unit проверки, Docker stack, health/ready и LLM smoke готовы.
Настоящий Telegram Guest Mode smoke не выполнен, потому что нужен ручной вызов `guest_message` через Telegram.

`BLOCKED_NEEDS_MANUAL_GUEST_MODE_TEST`
