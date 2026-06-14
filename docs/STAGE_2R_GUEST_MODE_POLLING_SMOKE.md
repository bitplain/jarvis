# Stage 2R Guest Mode Polling Smoke

## Зачем polling

Telegram Bot API получает updates одним из двух взаимоисключающих способов:

- webhook через `setWebhook`;
- polling через `getUpdates`.

Для локального Mac без публичного HTTPS URL tunnel не нужен: webhook удаляется, затем локальный процесс получает updates напрямую через polling.

## Подготовка `.env`

В локальном `.env` должны быть реальные значения Telegram и LLM.
Не коммитить `.env`.

Для host-side polling на Mac Docker hostnames обычно недоступны, поэтому нужны overrides:

```env
POSTGRES_HOST=localhost
REDIS_URL=redis://localhost:6379/0
GUEST_MODE_ENABLED=true
GUEST_MODE_ADMIN_ONLY=true
```

Пример без секретов: `.env.polling.example`.
Локальный `docker-compose.override.yml` публикует Postgres `5432` и Redis `6379`, чтобы host-side polling runner мог подключиться к сервисам на Mac.

## Поднять runtime

```bash
docker compose up -d postgres redis worker
docker compose up -d api
docker compose exec api alembic upgrade head
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8000/ready
```

## Readiness без получения updates

Readiness script удаляет webhook, проверяет `getMe`, Postgres, Redis, Guest Mode env и LLM smoke.
Он не вызывает `getUpdates`, чтобы не съесть ручной `guest_message`.

```bash
uv run --python 3.12 --extra dev python scripts/smoke_polling_readiness.py
```

Ожидаемый verdict:

```text
PASS_POLLING_READINESS
```

## Запуск polling

```bash
uv run --python 3.12 --extra dev python scripts/run_polling.py
```

По умолчанию pending updates сохраняются:

```text
drop_pending_updates=false
```

Удалять pending updates можно только явным флагом:

```bash
uv run --python 3.12 --extra dev python scripts/run_polling.py --drop-pending-updates
```

## Ручной Guest Mode вызов

В Telegram вызвать бота именно как guest-бота в чате, куда он НЕ добавлен:

```text
@bot_username кратко объясни, что такое DNS
```

Потом сделать reply на любое сообщение и отправить:

```text
@bot_username кратко перескажи это
```

Обычная личка, обычная группа с добавленным ботом и group mention не считаются Stage 2 Guest Mode smoke.
Засчитывается только update type `guest_message`.

## Проверка логов

Проверить polling runner output и runtime logs:

```bash
docker compose logs --tail=500 worker
docker compose logs --tail=500 api
```

Нужно подтвердить:

- пришёл `guest_message`;
- есть `guest_query_id`;
- ответ ушёл через `answerGuestQuery`;
- пользователь получил ответ в Telegram;
- обычная chat memory не использовалась.

## Проверка БД

Не выводить приватные тексты полностью.

```bash
docker compose exec postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
  "select id, telegram_update_id, status, provider, model, error_code, replied_text is not null as has_reply, answered_at is not null as answered from guest_messages_stub order by id desc limit 5;"
```

Ожидаемо:

- запись без reply;
- запись с reply, если Telegram передал replied text;
- `status=answered`;
- `provider` и `model` заполнены;
- `error_code` пустой при успехе.

## Verdict

- `PASS_STAGE_2_GUEST_MODE_REAL_READY` — polling получил настоящий `guest_message`, был `guest_query_id`, ответ ушёл через `answerGuestQuery`, БД проверена.
- `PASS_STAGE_2R_POLLING_READY_NEEDS_MANUAL_GUEST_TEST` — polling runner готов, но ручной guest-вызов ещё не выполнен.
- `BLOCKED_GUEST_MODE_NOT_ENABLED_IN_TELEGRAM` — polling работает, но Telegram не присылает `guest_message`.
- `BLOCKED_TELEGRAM_CLIENT_DID_NOT_SEND_GUEST_MESSAGE` — пришёл обычный `message`, а не `guest_message`.
- `PARTIAL_STAGE_2_GUEST_UPDATE_RECEIVED_REPLY_FAILED` — `guest_message` пришёл, но ответ не отправился.
- `PARTIAL_STAGE_2_GUEST_DB_CHECK_FAILED` — ответ есть, но БД не подтвердила запись.
