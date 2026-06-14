# Архитектура Stage 1

## Компоненты

- `api` — FastAPI приложение с health, ready, Telegram webhook и admin diagnostics.
- `worker` — arq worker, который выполняет LLM generation jobs.
- `postgres` — хранилище пользователей, чатов, сообщений, LLM-запросов и stub-событий.
- `redis` — очередь arq.
- `llm` — общий интерфейс провайдеров и fallback Yandex -> OpenRouter.

## Поток Telegram private chat

1. Telegram отправляет update в `POST /telegram/webhook`.
2. FastAPI проверяет webhook secret и передаёт update в aiogram Dispatcher.
3. Middleware пропускает только `ADMIN_TELEGRAM_IDS`.
4. Private handler сохраняет входящее сообщение в PostgreSQL.
5. Handler ставит arq job `process_llm_message`.
6. Worker собирает system prompt и последние `MEMORY_MAX_MESSAGES`.
7. Worker вызывает LLM provider.
8. В private chat worker пробует `sendMessageDraft`; при недоступности использует `sendChatAction typing`.
9. После генерации worker отправляет финальный `sendMessage` и сохраняет только финальный ответ.

## Поток групп

Бот отвечает только если его явно упомянули через `@bot_username` или сообщение является reply на сообщение бота. Streaming в группах не используется.

## Guest Mode

Guest Mode обрабатывает Telegram update type `guest_message` через отдельный aiogram router.
Роутер извлекает `guest_query_id`, текст guest-вызова, caller user/chat и replied message, если Telegram их передал.
Если `guest_query_id` отсутствует, бот не отвечает и сохраняет диагностический `ignored` record.

Guest Mode по умолчанию выключен: `GUEST_MODE_ENABLED=false`.
При `GUEST_MODE_ADMIN_ONLY=true` LLM вызывается только для caller user из `ADMIN_TELEGRAM_IDS`; если Telegram не передал caller user id, возвращается отказ владельца.
Ответ отправляется только одним финальным `answerGuestQuery` через typed aiogram method.
Streaming, `sendMessageDraft`, обычная chat memory и постоянная память чужого guest-чата в этом потоке не используются.

Guest prompt содержит только текст guest-вызова и replied message.
Если replied message недоступен, prompt требует честно сказать, что контекста не видно, когда пользователь ссылается на "это", "выше" или "предыдущее".

## LLM

Публичный контракт:

- `LLMProvider`
- `LLMMessage`
- `LLMResponse`
- `LLMStreamChunk`

Yandex и OpenRouter используют OpenAI-compatible HTTP API. Base URL, API key и model берутся только из env. Fallback пробует OpenRouter после retryable ошибок Yandex: auth, rate limit, network, server, unavailable model.

## Streaming

`StreamBuffer` не даёт отправлять обновление на каждый токен. Draft обновляется не чаще заданного интервала или после накопления достаточного числа символов. Draft не считается постоянным сообщением и не пишется в БД.

## Business Mode / Secretary Foundation

Stage 3A обрабатывает Telegram Business updates через отдельный router `app/bot/routers/business.py`.
Поддержанные update types:

- `business_connection`
- `business_message`
- `edited_business_message`
- `deleted_business_messages`

`business_connection` сохраняется в таблицу `business_connections` с состоянием `enabled`, `disabled`, `ignored` или `failed`.
Роутер извлекает `business_connection_id`, owner user id, `user_chat_id`, `is_enabled` и права, включая `can_reply` и `can_read_messages`.
При `BUSINESS_ADMIN_ONLY=true` connection активируется только если owner user id входит в `ADMIN_TELEGRAM_IDS`.

`business_message` сохраняется в таблицу `business_messages`.
Ответ запрещён, если выключен `BUSINESS_MODE_ENABLED`, connection не найден и не получен через `getBusinessConnection`, connection disabled/ignored, `can_reply=false`, выключен `BUSINESS_REPLY_ENABLED`, chat/connection не в allowlist или текст не начинается с `BUSINESS_REPLY_TRIGGER`.

Когда все guards пройдены, `BusinessService` убирает trigger, строит русский краткий prompt и вызывает LLM.
Ответ отправляется typed aiogram `sendMessage` с `business_connection_id`.
Outgoing response сохраняется отдельной записью `direction=outgoing`.

Business memory не смешивается с обычной chat memory и Guest Mode.
Для prompt берутся последние `BUSINESS_MEMORY_MAX_MESSAGES` записей только по `business_connection_id + chat_id`.
Edited/deleted business events только пишутся в audit trail и обновляют найденные исходные сообщения; автоматического ответа на них нет.

## Stubs

Guest Mode реализован в Stage 2 и хранит записи в совместимой таблице `guest_messages_stub`.
Autonomous Secretary auto-reply и Mini App остаются будущими этапами.

## Безопасность

Секреты не хардкодятся, не логируются и не попадают в git. Пользователю показываются короткие русские ошибки, технические детали остаются в server logs без секретов.
Business reports/status не выводят полный `business_connection_id`, Telegram IDs, токены, ключи или приватные тексты business-сообщений.
