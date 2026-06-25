# Railway deploy Jarvis

Stage 4B готовит репозиторий к ручному production deploy на Railway.
Этот документ не создаёт Railway project и не запускает deploy сам по себе.

## 1. Что будет создано в Railway

- API service: FastAPI webhook backend, публичный домен, healthcheck `/ready`.
- Worker service: arq worker без public domain.
- PostgreSQL: Railway PostgreSQL plugin/service.
- Redis: Railway Redis plugin/service.

Railway не запускает `docker-compose.yml` как единый production stack. Compose остаётся локальным development flow.

## 2. Создать Railway project

1. Открыть Railway dashboard.
2. Создать новый project.
3. Не вставлять секреты в git, README, issue, PR или logs.
4. Подключить GitHub repository Jarvis как source.

## 3. Подключить GitHub repo

В Railway выбрать GitHub repo Jarvis и создать первый service для API.
Если Railway UI позволяет выбрать config file, API service uses `railway.api.toml`.
Если UI не даёт выбрать toml, использовать тот же Dockerfile и вручную задать Start Command:

```bash
sh -c 'uvicorn app.main:app --host ${APP_HOST:-0.0.0.0} --port ${PORT:-8000}'
```

## 4. PostgreSQL и Redis

1. Добавить Railway PostgreSQL.
2. Добавить Railway Redis.
3. Подключить variables этих services к API service и Worker service.
4. Для PostgreSQL использовать `DATABASE_URL`, который Railway отдаёт сервису.
5. Для Redis использовать `REDIS_URL`, который Railway отдаёт сервису.

Jarvis принимает `DATABASE_URL` в формате Railway и приводит `postgresql://` / `postgres://` к async driver `postgresql+asyncpg://`.

## 5. Variables

Добавить в Railway Variables для API и Worker:

```env
APP_ENV=production
APP_HOST=0.0.0.0
APP_PORT=8000
PUBLIC_BASE_URL=https://your-service.up.railway.app

TELEGRAM_BOT_TOKEN=
TELEGRAM_BOT_USERNAME=
TELEGRAM_WEBHOOK_SECRET=
ADMIN_TELEGRAM_IDS=
ADMIN_API_TOKEN=

DATABASE_URL=
REDIS_URL=

LLM_PRIMARY_PROVIDER=yandex
LLM_FALLBACK_PROVIDER=openrouter

YANDEX_AI_BASE_URL=
YANDEX_AI_API_KEY=
YANDEX_AI_FOLDER_ID=
YANDEX_AI_MODEL=

OPENROUTER_BASE_URL=
OPENROUTER_API_KEY=
OPENROUTER_MODEL=

GUEST_MODE_ENABLED=true
GUEST_MODE_ADMIN_ONLY=true

STREAMING_ENABLED=true
STREAMING_PRIVATE_DRAFT_ENABLED=true
STREAMING_GROUP_FALLBACK_ENABLED=true
STREAMING_DRAFT_UPDATE_INTERVAL_MS=800
STREAMING_GROUP_EDIT_INTERVAL_MS=1000
STREAMING_MIN_CHARS_DELTA=120
STREAMING_MAX_DRAFT_SECONDS=25
STREAMING_SEND_CHAT_ACTION_INTERVAL_SECONDS=4
STREAMING_DRAFT_RAW_API_FALLBACK=true
```

Значения выше являются именами и безопасными defaults/placeholders. Реальные token/key/admin values вводятся только в Railway Variables.

## 6. API service

- Source: тот же GitHub repo.
- Build: Dockerfile.
- Railway config: `railway.api.toml`.
- Start Command:

```bash
sh -c 'uvicorn app.main:app --host ${APP_HOST:-0.0.0.0} --port ${PORT:-8000}'
```

- Public domain: включить.
- Healthcheck path: `/ready`.
- Проверочный endpoint без зависимостей: `/health`.
- Telegram webhook endpoint: `/telegram/webhook`.

## 7. Worker service

- Source: тот же GitHub repo.
- Build: Dockerfile.
- Railway config: `railway.worker.toml`.
- Public domain: не нужен.
- Start Command:

```bash
arq app.workers.arq_settings.WorkerSettings
```

Worker подключается к PostgreSQL и Redis через те же Railway Variables. Worker не запускает Alembic migrations автоматически.

## 8. Миграции

Предпочтительный flow: ручная миграция через Railway CLI после настройки variables и перед проверкой webhook:

```bash
railway run alembic upgrade head
```

Не запускать миграции автоматически в worker, чтобы не получить гонки между services.

## 9. Установить webhook

После получения публичного Railway domain и заполнения `PUBLIC_BASE_URL`:

```bash
railway run python scripts/setup_telegram_webhook.py
railway run python scripts/setup_telegram_webhook.py --info
```

Скрипт берёт `TELEGRAM_BOT_TOKEN`, `PUBLIC_BASE_URL` и `TELEGRAM_WEBHOOK_SECRET` из Railway process env или локального `.env`. В выводе показываются только sanitized host/path/status, без token и secret.

## 10. Проверить

HTTP:

```bash
curl -fsS https://your-service.up.railway.app/health
curl -fsS https://your-service.up.railway.app/ready
```

Telegram:

- `/start` в private chat.
- Private assistant: обычный текст владельца.
- Guest Mode: вызов через `@bot_username`, который Telegram доставляет как `guest_message`.
- Group assistant: mention/reply в настоящей group/supergroup, где бот добавлен участником.
- Streaming private draft: private path создаёт draft preview и финальный ответ.
- Group fallback streaming: group path использует provisional/edit flow, без `sendMessageDraft`.

Repository readiness без секретов:

```bash
railway run python scripts/smoke_railway_readiness.py
```

## 11. Logs

В Railway смотреть отдельно:

- API service logs: startup, `/health`, `/ready`, Telegram webhook POST, sanitized errors.
- Worker service logs: arq startup, `process_llm_message`, provider status без token/key/header.
- PostgreSQL/Redis service status: connection errors и restarts.

В логах нельзя печатать Telegram token, provider keys, Authorization headers, `ADMIN_API_TOKEN`, полные Telegram IDs и приватный текст сообщений.

## 12. Откатиться

1. В Railway выбрать предыдущий deployment API service.
2. В Railway выбрать предыдущий deployment Worker service.
3. Если откат затрагивает schema, отдельно оценить Alembic downgrade/restore snapshot.
4. Проверить `/health`, `/ready`, webhook info и один private smoke.

## 13. Что нельзя делать

- Не включать polling в production; polling только для local/Mac smoke.
- Не хранить `.env` в git.
- Не запускать два Telegram runtime одновременно: webhook production и local polling.
- Не создавать Railway project/deploy без отдельной команды.
- Не пушить изменения, tag или release без отдельной команды.
