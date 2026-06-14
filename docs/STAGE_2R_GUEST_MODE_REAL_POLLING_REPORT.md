# Stage 2R Real Guest Mode Polling Report

## Контекст

- Стартовый commit: `33ab735 Stage 2R: add local polling smoke for Guest Mode`.
- Цель: проверить настоящий Telegram Guest Mode через локальный polling runner без tunnel и без webhook.
- Обычная личка, обычная группа, group mention и synthetic updates не засчитывались.

## Polling runner

- Команда: `uv run --python 3.12 --extra dev python scripts/run_polling.py`.
- Webhook удалён перед polling: да, через `deleteWebhook`.
- `drop_pending_updates`: `false`.
- `allowed_updates` содержит `guest_message`: да.
- Guest Mode: enabled.
- Admin-only: enabled.
- Runner остановлен штатно после ручного smoke.

## Telegram guest updates

- Настоящий `guest_message` пришёл: да, подтверждено созданием свежих записей в `guest_messages_stub` через guest router/service path.
- `guest_query_id` был: да, иначе записи были бы `ignored`; все свежие записи завершились `answered`.
- Ответ через `answerGuestQuery`: да, ошибок `guest_answer_failed` в polling output не было, пользователь подтвердил получение ответов в Telegram.
- Guest-вызов без reply: успешный ответ, свежая запись `answered`, `has_reply=false`.
- Guest-вызов с reply: успешный ответ, свежие записи `answered`, `has_reply=true`.
- Обычная chat memory для guest path не использовалась; guest records сохранены отдельно в `guest_messages_stub`.

## PostgreSQL

Проверка без вывода приватных текстов:

- fresh guest records за окно проверки: `3`.
- `status=answered`: `3`.
- `error_code` пустой: `3`.
- `provider`: `yandex`.
- `model`: зафиксирована в БД.
- records с `replied_text`: `2`.
- records без `replied_text`: `1`.
- records с `response_text`: `3`.

Во время проверки также были обычные Telegram updates до/между guest-вызовами; они не засчитывались как Guest Mode.

## LLM smoke

`scripts/smoke_llm.py`:

- `yandex: OK`.
- `openrouter: OK`.
- `forced_fallback: OK`.
- verdict: `PASS_LLM_SMOKE`.

## Финальные проверки

Выполнено:

```bash
uv run --python 3.12 --extra dev ruff check .
uv run --python 3.12 --extra dev mypy app
uv run --python 3.12 --extra dev pytest -q
docker compose build
docker compose up -d
docker compose exec api alembic upgrade head
docker compose exec api pytest -q
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8000/ready
git status --short
```

Результаты:

- `ruff check .` — PASS.
- `mypy app` — PASS, `47 source files`.
- local `pytest -q` — PASS, `45 passed`.
- `docker compose build` — PASS.
- `docker compose up -d` — PASS.
- `docker compose exec api alembic upgrade head` — PASS.
- container `pytest -q` — PASS, `45 passed`.
- `/health` — `{"status":"ok"}`.
- `/ready` — `{"status":"ok","checks":{"postgres":true,"redis":true}}`.
- `docker compose ps` — `api`, `postgres`, `redis` healthy; `worker` running.
- `git status --short` — только staged documentation changes перед commit.

## Verdict

`PASS_STAGE_2_GUEST_MODE_REAL_READY`
