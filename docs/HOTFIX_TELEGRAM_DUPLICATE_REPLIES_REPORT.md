# Hotfix Telegram Duplicate Replies

Дата: 2026-06-26

## Симптом

После rotation Telegram bot token production bot начал отвечать по несколько раз на одно private сообщение:

- на `Привет` пришло 4 разных LLM ответа;
- на `Тест` пришло 4 разных LLM ответа.

Это не cosmetic logging issue, а duplicate processing: один Telegram message мог создать несколько `process_llm_message` jobs.

## Root cause evidence

Локальная проверка `main` до fix показала:

- `POST /telegram/webhook` всегда вызывал `dispatcher.feed_update(...)` для каждого HTTP delivery;
- Redis/DB guard по Telegram `update_id` отсутствовал;
- private/group routers ставили `process_llm_message` без стабильного arq `job_id`;
- regression tests с повторной отправкой одного и того же `update_id` падали: один update дважды доходил до Dispatcher, дважды enqueue-ил LLM job и дважды отправлял `Думаю`/group action.

Это объясняет production symptom при Telegram retry, pending duplicate delivery или повторной доставке после webhook/token transition. Live Railway facts по replica count, exact repeated webhook count и token parity нужно подтвердить отдельно в Railway UI/logs без вывода секретов.

## Fix

- В `app/api/routes_telegram.py` добавлен Redis idempotency guard:
  - key: `telegram:update:<update_id>`;
  - operation: `SET NX`;
  - TTL: 10 минут;
  - duplicate delivery возвращает `200 OK`, пишет sanitized `telegram_webhook_duplicate_update_skipped` и не вызывает Dispatcher.
- При Redis failure guard работает fail-open:
  - логирует sanitized `telegram_webhook_dedup_unavailable`;
  - продолжает webhook processing, чтобы Redis outage не ломал `/start` и settings callbacks.
- Private/group LLM enqueue теперь использует стабильный arq `_job_id=llm:<chat_id>:<message_id>`.
- Логи не содержат token, webhook secret, Authorization headers, полный Telegram update или текст сообщения.

## Tests

Добавлены regression tests:

- duplicate private update id -> один `process_llm_message`, один `Думаю`;
- duplicate group mention update id -> один `process_llm_message`, один chat action;
- duplicate `/start` update id -> один ответ `/start`;
- Redis dedup failure -> update всё равно проходит в Dispatcher;
- readiness smoke `scripts/smoke_telegram_update_idempotency_readiness.py`.

## Live verification

Не выполнялась в этом hotfix branch:

- Railway Variables не менялись;
- `deleteWebhook` не вызывался;
- Telegram API destructive calls не выполнялись;
- новые сообщения пользователю в бот не отправлялись.

После merge/deploy нужно проверить одним ручным Telegram message:

1. отправить один `Привет`;
2. в logs увидеть один accepted update или duplicate skip for same `update_id`;
3. увидеть один `process_llm_message` job;
4. получить ровно один final Telegram answer.

## Verdict

`PASS_HOTFIX_TELEGRAM_DUPLICATE_REPLIES_CODE_READY`

Live verdict остаётся `BLOCKED_NEEDS_RAILWAY_AND_TELEGRAM_EVIDENCE` до production deploy/log evidence.
