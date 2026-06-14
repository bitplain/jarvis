# Stage 3A Business Mode Real Smoke

## Цель

Проверить настоящий Telegram Business Mode без включения постоянного автоответчика.
Smoke засчитывается только если Telegram прислал настоящие `business_connection` и `business_message`, а тестовый ответ отправлен через `business_connection_id`.

## 1. Включить Secretary / Business Mode в BotFather

1. Открыть BotFather.
2. Выбрать бота Jarvis.
3. Включить Telegram Business / Business Mode, если этот пункт доступен для бота.
4. Не публиковать token или другие секреты в чат, docs, logs или commit.

## 2. Подключить бота к Telegram Business account

1. Открыть настройки Telegram Business account владельца.
2. Подключить бота Jarvis как business bot.
3. Выдать минимальные права для Stage 3A:
   - обязательно: `can_reply`;
   - желательно для будущих этапов: `can_read_messages`.
4. Убедиться, что owner user id входит в `ADMIN_TELEGRAM_IDS`.

## 3. Локальный env для ручного smoke

В локальном `.env` включить только guarded режим:

```env
BUSINESS_MODE_ENABLED=true
BUSINESS_ADMIN_ONLY=true
BUSINESS_REPLY_ENABLED=true
BUSINESS_REPLY_TRIGGER=!jarvis
BUSINESS_MEMORY_MAX_MESSAGES=10
```

Allowlist можно оставить пустым или ограничить вручную после первого диагностического connection event:

```env
BUSINESS_ALLOWED_CONNECTION_IDS=
BUSINESS_ALLOWED_CHAT_IDS=
```

Реальные значения `.env` не коммитить.

## 4. Readiness без получения updates

```bash
uv run --python 3.12 --extra dev python scripts/smoke_business_readiness.py
```

Скрипт проверяет sanitized env status, Telegram `getMe`, PostgreSQL, Redis, LLM smoke и наличие business update types в polling runner.
Он не вызывает `getUpdates`.

## 5. Запустить polling

```bash
uv run --python 3.12 --extra dev python scripts/run_polling.py
```

Polling runner должен стартовать с `allowed_updates`:

```text
business_connection, business_message, edited_business_message, deleted_business_messages, guest_message, message, edited_message, callback_query
```

## 6. Отправить тестовое сообщение

В business chat отправить:

```text
!jarvis кратко ответь, что сообщение получено
```

Сообщения без trigger `!jarvis` не должны получать ответ.

## 7. Проверить результат

Проверить без вывода приватных текстов и полных identifiers:

- пришёл `business_connection` update;
- пришёл `business_message` update;
- ответ отправлен через `business_connection_id`;
- в `business_connections` есть запись со статусом `enabled`;
- в `business_messages` есть входящая запись `answered`;
- в `business_messages` есть outgoing response;
- `/status` показывает Business Mode/Reply/Admin Only и counts.

Если ручное подключение Telegram Business ещё не выполнено, verdict:

`BLOCKED_NEEDS_MANUAL_BUSINESS_MODE_TEST`
