# Stage 2 Guest Mode Real Smoke

## Что проверяется

Проверяется именно Telegram Guest Mode update type `guest_message`, а не обычное сообщение в личке или группе.
Обычный private/group message не засчитывается как Stage 2 real smoke.

## Подготовка

1. В `.env` должны быть реальные локальные значения Telegram и LLM.
2. Guest Mode должен быть включён явно:

```env
GUEST_MODE_ENABLED=true
GUEST_MODE_ADMIN_ONLY=true
```

3. `ADMIN_TELEGRAM_IDS` должен содержать Telegram user id владельца.
4. Webhook должен смотреть на публичный HTTPS URL локального API:

```bash
uv run --python 3.12 --extra dev python scripts/set_telegram_webhook.py
uv run --python 3.12 --extra dev python scripts/set_telegram_webhook.py --info
```

5. Если Telegram требует отдельного включения Guest Mode, включить его в BotFather или настройках Telegram-клиента для бота.

## Локальный Mac без tunnel

Если публичный HTTPS tunnel недоступен, использовать polling вместо webhook:

```bash
uv run --python 3.12 --extra dev python scripts/smoke_polling_readiness.py
uv run --python 3.12 --extra dev python scripts/run_polling.py
```

Подробная инструкция: `docs/STAGE_2R_GUEST_MODE_POLLING_SMOKE.md`.

Polling удаляет webhook через `deleteWebhook` и не требует tunnel.
Readiness script не вызывает `getUpdates`, чтобы не съесть ручной `guest_message`.

## Вызов без reply

В другом чате, где бот не добавлен как обычный участник, вызвать:

```text
@bot_username кратко перескажи это
```

Ожидаемо: бот отвечает одним финальным guest-ответом.

## Вызов с reply

1. В другом чате ответить на существующее сообщение.
2. В reply написать:

```text
@bot_username переведи это нормально
```

Ожидаемо: бот учитывает только текст вызова и replied message.

## Проверка логов

```bash
docker compose logs --tail=100 api
docker compose logs --tail=100 worker
```

В логах не должно быть Telegram token, LLM API keys, Authorization headers, паролей или реальных env secrets.

## Проверка БД

```bash
docker compose exec postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
  "select id, telegram_update_id, status, provider, model, error_code, created_at, answered_at from guest_messages_stub order by id desc limit 5;"
```

Проверять только статусные поля и hash/masked identifiers.
Приватные тексты запроса и reply не выводить в отчёт полностью.

## Ограничения Guest Mode

- Нет истории чужого чата.
- Нет списка участников.
- Нет постоянной памяти чужого чата.
- Нет streaming.
- Нет `sendMessageDraft`.
- Нет ответа без `guest_query_id`.

## Возможные verdict

- `PASS_STAGE_2_GUEST_MODE_REAL_READY` — Telegram прислал `guest_message`, ответ отправлен через `answerGuestQuery`, запись появилась в БД.
- `BLOCKED_NEEDS_MANUAL_GUEST_MODE_TEST` — код готов, но нужен ручной вызов через Telegram.
- `BLOCKED_GUEST_MODE_NOT_ENABLED_IN_TELEGRAM` — Telegram не присылает `guest_message`.
