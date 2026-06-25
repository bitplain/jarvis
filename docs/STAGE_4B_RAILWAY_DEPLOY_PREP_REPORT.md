# Stage 4B Railway Deploy Prep Report

## Verdict

`PASS_STAGE_4B_RAILWAY_DEPLOY_PREP_READY`

Репозиторий подготовлен к ручному созданию Railway services. Railway project, deploy, push, tag и release не выполнялись.

## Что добавлено

- `railway.api.toml` — Railway config для API/webhook service.
- `railway.worker.toml` — Railway config для arq worker service.
- `docs/RAILWAY_DEPLOY.md` — пошаговая инструкция Railway deploy.
- `scripts/smoke_railway_readiness.py` — repository readiness smoke без вывода секретов.
- `scripts/setup_telegram_webhook.py` — совместимое имя для существующего sanitized webhook script.
- `tests/test_railway_deploy.py` — deploy-contract tests.

## Что изменено

- `Dockerfile`: default CMD теперь слушает Railway `$PORT`, с fallback на `APP_PORT`/`8000`.
- `app/core/config.py`: добавлена поддержка Railway `DATABASE_URL` с нормализацией `postgresql://` / `postgres://` в `postgresql+asyncpg://`.
- `scripts/set_telegram_webhook.py`: теперь читает Railway process env и локальный `.env`, вывод остаётся sanitized.
- `.env.example`: добавлены Railway-compatible variables и production placeholders/defaults.
- `README.md`: добавлен раздел `Deployment`.
- `AGENTS.md`: добавлены Stage 4B Railway deploy boundaries.
- Тестовые и исторические docs-строки очищены от token/header-shaped false positives для security scan.

## Railway services

- API service:
  - config: `railway.api.toml`;
  - build: Dockerfile;
  - start command: `sh -c 'uvicorn app.main:app --host ${APP_HOST:-0.0.0.0} --port ${PORT:-8000}'`;
  - public domain: нужен;
  - Railway deploy healthcheck path: `/health`;
  - dependency readiness endpoint: `/ready`.
- Worker service:
  - config: `railway.worker.toml`;
  - build: Dockerfile;
  - start command: `arq app.workers.arq_settings.WorkerSettings`;
  - public domain: не нужен.
- Railway PostgreSQL:
  - передаёт `DATABASE_URL` в API и Worker.
- Railway Redis:
  - передаёт `REDIS_URL` в API и Worker.

## Env variables

Минимальный набор описан в `.env.example` и `docs/RAILWAY_DEPLOY.md`:

- app/public: `APP_ENV`, `APP_HOST`, `APP_PORT`, `PUBLIC_BASE_URL`;
- Telegram/admin: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_USERNAME`, `TELEGRAM_WEBHOOK_SECRET`, `ADMIN_TELEGRAM_IDS`, `ADMIN_API_TOKEN`;
- data services: `DATABASE_URL`, `REDIS_URL`;
- LLM: `LLM_PRIMARY_PROVIDER`, `LLM_FALLBACK_PROVIDER`, `YANDEX_AI_*`, `OPENROUTER_*`;
- modes: `GUEST_MODE_*`, `STREAMING_*`.

Все реальные значения должны задаваться только через Railway Variables или локальный `.env`.

## Migration flow

Выбран вариант A: миграции запускаются вручную через Railway CLI, не автоматически в worker.

```bash
railway run alembic upgrade head
```

## Webhook flow

После настройки public domain и `PUBLIC_BASE_URL`:

```bash
railway run python scripts/setup_telegram_webhook.py
railway run python scripts/setup_telegram_webhook.py --info
```

Скрипт не печатает Telegram token, webhook secret или реальные env secrets.

## Проверки

- `uv run --python 3.12 --extra dev ruff check .` — PASS.
- `uv run --python 3.12 --extra dev mypy app` — PASS, no issues in 52 source files.
- `uv run --python 3.12 --extra dev pytest -q` — PASS, 129 passed.
- `uv run --python 3.12 --extra dev python scripts/smoke_railway_readiness.py` — PASS_RAILWAY_READINESS.
- Security scan command — PASS, совпадений в tracked files нет.
- `docker compose build` — BLOCKED локально: Docker daemon/socket недоступен (`/Users/kaiot/.docker/run/docker.sock` отсутствует).
- `docker compose up -d`, `docker compose exec api alembic upgrade head`, `curl /health`, `curl /ready` — не запускались после Docker blocker.

## Что осталось сделать руками в Railway UI

1. Создать Railway project.
2. Подключить GitHub repo Jarvis.
3. Создать API service с `railway.api.toml` или тем же Dockerfile и Start Command из документации.
4. Создать Worker service с `railway.worker.toml` или тем же Dockerfile и worker Start Command.
5. Добавить Railway PostgreSQL и Railway Redis.
6. Привязать `DATABASE_URL` и `REDIS_URL` к API и Worker.
7. Заполнить Telegram/admin/LLM variables без публикации значений.
8. Запустить миграции.
9. Установить webhook.
10. Проверить `/health`, `/ready` и реальные Telegram flows.

## Что нельзя делать

- Не включать polling в production; polling только для local/Mac smoke.
- Не хранить `.env` в git.
- Не запускать одновременно production webhook runtime и local polling runtime.
- Не пушить, не создавать deploy/tag/release без отдельной команды.
