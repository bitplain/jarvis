# Stage 4C Railway live deployment

## Verdict

`PASS_STAGE_4C_RAILWAY_LIVE_DEPLOY_READY`

Stage 4C фиксирует live Railway bring-up и переводит миграции PostgreSQL из ручного шага в Railway API pre-deploy command. GitHub push, tag, release и изменение Railway Variables в этом stage не выполнялись.

## Base commit

`dc64750 Stage 4B: prepare Railway deployment`

## Railway project status

- API online: yes.
- Worker online: yes.
- PostgreSQL online: yes.
- Redis online: yes.

## API

- `/ready`: OK.
- webhook POST: OK.
- webhook info: OK.
- deploy healthcheck path: `/health`.

## Worker

- Redis connected: yes.
- `process_llm_message`: yes.
- private streaming selected: yes.
- draft calls: yes.
- final send: yes.

## Telegram

- `/start`: OK.
- private regular answer: OK.

## Database

- migrations manually applied during live bring-up: yes.
- automated migration added in this stage: yes, `railway.api.toml` содержит `preDeployCommand = "alembic upgrade head"`.
- worker migration run: no, worker остаётся только background worker и не запускает Alembic.

## Known Railway gotchas fixed/documented

- Start Command должен раскрывать `${PORT:-8080}` через `sh -c`, иначе `$PORT` может попасть в uvicorn как буквальная строка.
- Railway Variables UI принимает имя переменной слева и только value справа; `KEY=value` в value field ломает настройки.
- `DATABASE_URL` и `REDIS_URL` должны ссылаться на Railway Postgres/Redis services.
- `TELEGRAM_WEBHOOK_SECRET` допускает только `A-Z`, `a-z`, `0-9`, `_`, `-`.
- `TELEGRAM_BOT_USERNAME` должен быть username без `@`, не numeric id.
- `ADMIN_TELEGRAM_IDS` должен содержать Telegram user id администратора.
- API и worker имеют отдельные Variables.
- LLM keys нужны в `jarvis-worker`.
- `relation "messages" does not exist` означает, что миграции не применились до runtime обработки.

## Remaining manual actions

- Verify next GitHub auto-deploy after push.
- Verify pre-deploy migration runs in Railway logs.
- Optional group live smoke on Railway.

## Проверки Stage 4C

Локально должны проходить:

```bash
uv run --python 3.12 --extra dev ruff check .
uv run --python 3.12 --extra dev mypy app
uv run --python 3.12 --extra dev pytest -q
uv run --python 3.12 --extra dev python scripts/smoke_railway_readiness.py
```

Docker checks выполняются только если локальный Docker daemon доступен.
