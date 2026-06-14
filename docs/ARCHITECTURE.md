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

## LLM

Публичный контракт:

- `LLMProvider`
- `LLMMessage`
- `LLMResponse`
- `LLMStreamChunk`

Yandex и OpenRouter используют OpenAI-compatible HTTP API. Base URL, API key и model берутся только из env. Fallback пробует OpenRouter после retryable ошибок Yandex: auth, rate limit, network, server, unavailable model.

## Streaming

`StreamBuffer` не даёт отправлять обновление на каждый токен. Draft обновляется не чаще заданного интервала или после накопления достаточного числа символов. Draft не считается постоянным сообщением и не пишется в БД.

## Stubs

Guest Mode и Secretary Mode имеют отдельные router/service stubs. Они логируют/сохраняют факт события, но не отвечают пользователю и не имитируют готовые права.

## Безопасность

Секреты не хардкодятся, не логируются и не попадают в git. Пользователю показываются короткие русские ошибки, технические детали остаются в server logs без секретов.
