# Railway deploy Jarvis

Stage 4C фиксирует повторяемый production deploy на Railway после ручного live bring-up.
Документ не создаёт Railway project, не меняет Railway Variables и не запускает deploy сам по себе.

## Railway services

- `jarvis-api`: публичный API/webhook service. У него включён public domain, Telegram webhook указывает на `/telegram/webhook`, Railway healthcheck идёт в `/health`, ручная dependency-проверка идёт через `/ready`.
- `jarvis-worker`: background worker без public domain. Он читает jobs из Redis и выполняет LLM/Telegram отправку.
- PostgreSQL: Railway Postgres service. `DATABASE_URL` подключается к API и worker.
- Redis: Railway Redis service. `REDIS_URL` подключается к API и worker.

Railway не запускает `docker-compose.yml` как единый production stack. Compose остаётся локальным development/smoke flow.

## Local container runtime on this Mac

На рабочей Mac-машине Docker Desktop daemon/socket `~/.docker/run/docker.sock` может быть недоступен. Это не означает, что локальный container runtime полностью отсутствует, и не является самостоятельным blocker для Railway release readiness.

Перед выводом "Docker недоступен" сначала проверить Apple Container CLI:

```bash
command -v container
container --help
```

Primary local container runtime on this Mac can be Apple Container CLI. Docker Compose checks are optional when Docker daemon is unavailable. Если конкретная задача требует именно Docker Compose, это нужно честно указать как ограничение Docker Compose; если достаточно container runtime/build smoke, можно использовать `container`, если он доступен.

Railway/live checks are the deployment source of truth для production readiness: Railway deploy logs, `/health`, `/ready`, webhook behavior, worker logs и реальные Telegram flows важнее локального Docker Desktop socket.

## Config files

Для Railway services используются отдельные config-as-code файлы:

- API: `railway.api.toml`.
- Worker: `railway.worker.toml`.

Если Railway UI позволяет выбрать custom config file, для API указать `/railway.api.toml`, для worker указать `/railway.worker.toml`.

## Start commands

API command из `railway.api.toml`:

```bash
sh -c "alembic upgrade head && python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"
```

Worker command из `railway.worker.toml`:

```bash
arq app.workers.arq_settings.WorkerSettings
```

Важно: API command должен идти через `sh -c`, чтобы `${PORT:-8080}` был раскрыт shell runtime, а не передан в uvicorn буквальной строкой. `alembic upgrade head` выполняется автоматически перед стартом webhook runtime, поэтому новая таблица должна появляться без ручного запуска миграции.

Railway UI Start Command может переопределить `railway.api.toml`. Поэтому Stage 4E добавляет code-level startup migration guard в API startup path: даже если UI запустит только `uvicorn app.main:app`, API при `APP_ENV=production` сначала выполнит Alembic и только потом начнёт принимать webhook requests.

## Pre-deploy migrations

API service запускает Alembic до старта новой версии:

```bash
alembic upgrade head
```

Это задано в `railway.api.toml`:

```toml
[deploy]
preDeployCommand = "alembic upgrade head"
```

Кроме pre-deploy шага, API start command повторяет `alembic upgrade head` перед `uvicorn`. Повторный запуск идемпотентен: если схема уже обновлена, Alembic ничего не меняет.

Worker service не запускает Alembic migrations. Это уменьшает риск гонки между API и worker deploy.

Если Railway pre-deploy command падает с non-zero exit code, deployment не должен переходить к старту приложения. Следующий push нужно проверять по логам `jarvis-api`: там должен быть виден успешный pre-deploy step.

## Railway Variables UI rule

В Railway Variables:

- left field = variable name;
- right field = value only;
- value only, no KEY=value.

Правильно:

```text
Key: DATABASE_URL
Value: ${{Postgres.DATABASE_URL}}
```

Неправильно:

```text
Key: DATABASE_URL
Value: DATABASE_URL=${{Postgres.DATABASE_URL}}
```

Реальные token/key/admin values вводятся только в Railway Variables. Их нельзя писать в git, README, issue, PR или logs.

## Required API variables

Минимальный набор для `jarvis-api`:

```env
APP_ENV=production
APP_HOST=0.0.0.0
APP_PORT=8080
PUBLIC_BASE_URL=https://jarvis-production-786d.up.railway.app
TELEGRAM_BOT_TOKEN=<secret>
TELEGRAM_BOT_USERNAME=Home_ai_my_bot
TELEGRAM_WEBHOOK_SECRET=<A-Z-a-z-0-9_- only>
ADMIN_TELEGRAM_IDS=<telegram-user-id>
ADMIN_API_TOKEN=<secret>
DATABASE_URL=${{Postgres.DATABASE_URL}}
REDIS_URL=${{Redis.REDIS_URL}}
REGULAR_ASSISTANT_ENABLED=true
GROUP_ASSISTANT_ENABLED=true
GUEST_MODE_ENABLED=true
STREAMING_ENABLED=true
STREAMING_PRIVATE_DRAFT_ENABLED=true
STREAMING_GROUP_FALLBACK_ENABLED=true
```

`TELEGRAM_BOT_USERNAME` должен быть username без `@`, не numeric id.
`ADMIN_TELEGRAM_IDS` должен содержать Telegram user id администратора.
`TELEGRAM_WEBHOOK_SECRET` допускает только `A-Z`, `a-z`, `0-9`, `_`, `-`.

## Required worker variables

Минимальный набор для `jarvis-worker`:

```env
TELEGRAM_BOT_TOKEN=<same bot token>
DATABASE_URL=${{Postgres.DATABASE_URL}}
REDIS_URL=${{Redis.REDIS_URL}}
LLM_PRIMARY_PROVIDER=yandex
LLM_FALLBACK_PROVIDER=openrouter
YANDEX_AI_BASE_URL=https://llm.api.cloud.yandex.net
YANDEX_AI_API_KEY=<secret>
YANDEX_AI_FOLDER_ID=<folder-id>
YANDEX_AI_MODEL=<model>
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_API_KEY=<secret>
OPENROUTER_MODEL=<model>
STREAMING_ENABLED=true
STREAMING_PRIVATE_DRAFT_ENABLED=true
STREAMING_GROUP_FALLBACK_ENABLED=true
```

LLM keys нужны именно в `jarvis-worker`, потому что LLM job выполняет worker.

## Runtime provider settings

Stage 4D не требует менять Railway Variables для переключения активного агента. Админ открывает `/settings` или кнопку `Настройки` в Telegram и выбирает:

- `Auto`;
- `Yandex`;
- `OpenRouter`.

Выбор сохраняется в PostgreSQL runtime setting `active_llm_provider` и применяется worker к следующим сообщениям. `Auto` сохраняет env-based логику `LLM_PRIMARY_PROVIDER` + `LLM_FALLBACK_PROVIDER`.

Таблица `runtime_settings` создаётся автоматически через Alembic при production startup API service. Если пользователь нажмёт кнопку в коротком окне rollout до применения схемы, webhook не должен падать с 500: бот покажет безопасное сообщение о временной недоступности настроек.

Railway Variables всё равно должны быть заполнены в `jarvis-worker`: `YANDEX_*` и `OPENROUTER_*` нужны для фактического вызова провайдера. Если выбранный provider не настроен, пользователь получит безопасную ошибку, а worker залогирует sanitized error без token/key/header.

Production deploy этой функции произойдёт только после merge PR в `main`, ожидания CI и Railway production autodeploy.

## Webhook setup

После получения публичного Railway domain и заполнения `PUBLIC_BASE_URL` выполнить в Railway API console:

```bash
PYTHONPATH=/app python scripts/setup_telegram_webhook.py
PYTHONPATH=/app python scripts/setup_telegram_webhook.py --info
```

Скрипт берёт `TELEGRAM_BOT_TOKEN`, `PUBLIC_BASE_URL` и `TELEGRAM_WEBHOOK_SECRET` из Railway process env или локального `.env`. В выводе показываются только sanitized host/path/status, без token и secret.

Production runtime использует webhook mode. Polling разрешён только для local/Mac smoke и не должен работать параллельно с production webhook runtime.
Короткое правило для проверок: polling только для local, production только webhook.

## Health and readiness

HTTP:

```bash
curl -fsS https://jarvis-production-786d.up.railway.app/health
curl -fsS https://jarvis-production-786d.up.railway.app/ready
```

`/health` должен проходить сразу после старта процесса. `/ready` вернёт degraded/503, если Railway PostgreSQL или Redis ещё не подключены, variables не привязаны, миграции не применены или сеть ещё не готова.

## LLM smoke

В Railway worker console:

```bash
PYTHONPATH=/app python scripts/smoke_llm.py
```

Ожидаемо:

- verdict не `BLOCKED_LLM_SMOKE`;
- нет `provider_not_configured`;
- нет `TokenValidationError`;
- бот отвечает в Telegram.

## Telegram smoke

Проверить руками после webhook setup:

- `/start` в private chat.
- Private regular answer: обычный текст владельца.
- Guest Mode: вызов через `@bot_username`, который Telegram доставляет как `guest_message`.
- Group assistant: mention/reply в настоящей group/supergroup, где бот добавлен участником.
- Streaming private draft: private path создаёт draft preview и финальный ответ.
- Group fallback streaming: group path использует provisional/edit flow, без `sendMessageDraft`.

Обычное private/group сообщение не считается Guest Mode smoke.

## Repository readiness without secrets

Локальная проверка config/docs без секретов:

```bash
uv run --python 3.12 --extra dev python scripts/smoke_railway_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_provider_settings_readiness.py
```

Ожидаемый verdict:

```text
PASS_RAILWAY_READINESS
PASS_PROVIDER_SETTINGS_READINESS
```

## Typical Railway failures

| Симптом | Причина | Фикс |
| --- | --- | --- |
| `$PORT is not a valid integer` | Start Command передал `${PORT...}` в приложение буквально, без shell expansion. | Использовать `sh -c "python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"`. |
| `TELEGRAM_BOT_TOKEN missing` | Token не задан в variables нужного service. | Добавить `TELEGRAM_BOT_TOKEN` в `jarvis-api` и `jarvis-worker`, значение не печатать. |
| `TokenValidationError: Token is invalid` | В value field вставили `TELEGRAM_BOT_TOKEN=...`, пробелы или неправильный token. | В Railway Variables right field вводить только value. |
| `secret token contains unallowed characters` | `TELEGRAM_WEBHOOK_SECRET` содержит запрещённые символы. | Использовать только `A-Z`, `a-z`, `0-9`, `_`, `-`. |
| `Доступ запрещён` | Telegram user id не входит в `ADMIN_TELEGRAM_IDS` или задан numeric bot id вместо owner id. | Указать реальный Telegram user id администратора в `ADMIN_TELEGRAM_IDS`. |
| `relation "messages" does not exist` или `relation "runtime_settings" does not exist` | PostgreSQL migrations не применились до обработки webhook/job. | Проверить `preDeployCommand = "alembic upgrade head"` и start command `alembic upgrade head && python -m uvicorn...` в `railway.api.toml`, затем логи API deploy/startup. |
| `provider_not_configured` | LLM provider variables не заданы в worker service. | Добавить Yandex/OpenRouter variables в `jarvis-worker`. |
| `llm_failed` | Provider доступен, но запрос завершился ошибкой модели, сети или auth. | Проверить worker logs, provider status, model id и ключи без вывода секретов. |
| Railway logs show `[err]`, but task has `●` | Railway может помечать stderr как `[err]`, хотя task ещё выполняется. | Смотреть verdict, traceback, exit code и последующие строки; не считать один marker `[err]` падением без контекста. |

## Logs

В Railway смотреть отдельно:

- API service logs: startup, pre-deploy migration, `/health`, `/ready`, Telegram webhook POST, sanitized errors.
- Worker service logs: arq startup, `process_llm_message`, provider status без token/key/header.
- PostgreSQL/Redis service status: connection errors и restarts.

В логах нельзя печатать Telegram token, provider keys, Authorization headers, `ADMIN_API_TOKEN`, полные Telegram IDs и приватный текст сообщений.

## Rollback

1. В Railway выбрать предыдущий deployment API service.
2. В Railway выбрать предыдущий deployment Worker service.
3. Если откат затрагивает schema, отдельно оценить Alembic downgrade/restore snapshot.
4. Проверить `/health`, `/ready`, webhook info и один private smoke.

## Что нельзя делать

- Не включать polling в production.
- Не хранить `.env` в git.
- Не запускать два Telegram runtime одновременно: webhook production и local polling runtime.
- Не менять Railway Variables через CLI без отдельного подтверждения.
- Не пушить изменения, tag или release без отдельной команды.
