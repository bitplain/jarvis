# Stage 3A-R Regular Assistant Clarification Report

## Почему Business Mode optional

Telegram Secretary / Business Mode через Bot API не является обычным режимом для всех аккаунтов.
Он требует Telegram Business / Secretary connection, `business_connection`, прав `can_reply` и отправки через `business_connection_id`.

Без этого Bot API не может читать личные входящие сообщения обычного пользователя и не может отвечать от имени пользователя.
Jarvis не переходит к userbot/MTProto.

## Что поддерживается для обычного аккаунта

- Regular Assistant Mode в личке с ботом.
- Group Assistant Mode, если бот добавлен в группу и сообщение является mention/reply.
- Guest Mode через `@bot_username`, если Telegram присылает `guest_message`.
- Forwarded Message Assistant: пользователь пересылает сообщение боту, Jarvis сохраняет его как context item.
- Reply Draft Mode: пользователь пишет `Ответь на это:` и получает черновик, который сам копирует и отправляет.

## Env

Добавлены regular flags:

```env
REGULAR_ASSISTANT_ENABLED=true
FORWARDED_MESSAGE_ASSISTANT_ENABLED=true
DRAFT_REPLY_ENABLED=true
GROUP_ASSISTANT_ENABLED=true
```

Business env оставлен optional и помечен как требующий Telegram Business / Secretary Mode.

## Изменённые файлы

- `app/core/config.py`
- `.env.example`
- `app/services/regular_assistant_service.py`
- `app/bot/routers/private.py`
- `app/bot/routers/groups.py`
- `app/bot/routers/commands.py`
- `scripts/smoke_regular_readiness.py`
- `README.md`
- `docs/ARCHITECTURE.md`
- `AGENTS.md`

## Тесты

Добавлены:

- `tests/test_regular_assistant_modes.py`
- `tests/test_forwarded_message_assistant.py`
- `tests/test_status_modes.py`
- `tests/test_smoke_regular_readiness.py`

Обновлены:

- `tests/test_group_handler.py`
- `tests/test_run_polling_script.py`
- `tests/test_status_command.py`

Покрыто:

- `/status` показывает Business Mode как `optional/disabled` по умолчанию.
- Forwarded message сохраняется как context item.
- Draft reply prompt обрабатывается как черновик, без имитации отправки от имени пользователя.
- Обычный режим не требует Business env.
- Business Mode остаётся disabled по умолчанию.
- Guest Mode и group mode не сломаны.

## Readiness

Добавлен `scripts/smoke_regular_readiness.py`.
Он проверяет regular env flags, Telegram `getMe`, PostgreSQL, Redis, LLM smoke и считает disabled Business Mode нормальным optional состоянием.
Скрипт не требует Business account.

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
uv run --python 3.12 --extra dev python scripts/smoke_regular_readiness.py
git status --short
```

Результаты:

- `ruff check .` — PASS.
- `mypy app` — PASS, `49 source files`.
- local `pytest -q` — PASS, `79 passed`.
- `docker compose build` — PASS.
- `docker compose up -d` — PASS.
- `docker compose ps` — `api`, `postgres`, `redis` healthy; `worker` running.
- API logs — Uvicorn started без ошибок.
- Worker logs — arq worker started с `process_llm_message`.
- `docker compose exec api alembic upgrade head` — PASS, head уже применён.
- container `pytest -q` — PASS, `79 passed`.
- `/health` — `{"status":"ok"}`.
- `/ready` — `{"status":"ok","checks":{"postgres":true,"redis":true}}`.
- `scripts/smoke_llm.py` — `PASS_LLM_SMOKE`.
- `scripts/smoke_polling_readiness.py` — `PASS_POLLING_READINESS`.
- `scripts/smoke_regular_readiness.py` — `PASS_REGULAR_READINESS`.
- `git status --short` — только ожидаемые Stage 3A-R изменения перед commit, `.env` не изменён.

## Verdict

`PASS_STAGE_3A_R_REGULAR_ASSISTANT_READY`
