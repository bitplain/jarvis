# Архитектура Jarvis

## Компоненты

- `api` — FastAPI приложение с health, ready, Telegram webhook и admin diagnostics.
- `worker` — arq worker, который выполняет LLM generation jobs.
- `postgres` — хранилище пользователей, чатов, сообщений, LLM-запросов и stub-событий.
- `redis` — очередь arq.
- `llm` — общий интерфейс провайдеров и fallback Yandex -> OpenRouter.

## Regular Assistant Mode

Regular Assistant Mode — основной путь для обычного Telegram-аккаунта.
Он не требует Telegram Business и работает только с теми сообщениями, которые пользователь явно отправил или переслал боту.

Bot API не позволяет читать личные входящие сообщения обычного пользователя и не позволяет отвечать от имени пользователя без Telegram Business / Secretary connection.
Jarvis не использует userbot/MTProto.

## Поток Telegram private chat

1. Telegram отправляет update в `POST /telegram/webhook`.
2. FastAPI проверяет webhook secret и передаёт update в aiogram Dispatcher.
3. Middleware пропускает только `ADMIN_TELEGRAM_IDS`.
4. Private handler сохраняет входящее сообщение в PostgreSQL.
5. Handler ставит arq job `process_llm_message`.
6. Worker собирает system prompt и последние `MEMORY_MAX_MESSAGES`.
7. Worker вызывает LLM provider через streaming interface, если `STREAMING_ENABLED=true`.
8. В private chat worker пробует Telegram `sendMessageDraft` с non-zero `draft_id`.
9. `StreamBuffer` обновляет draft не на каждый token, а по интервалу, приросту текста, границе предложения или финалу.
10. Если draft API недоступен, текущий job переключается на fallback sink.
11. После генерации worker отправляет финальный `sendMessage` и сохраняет только финальный ответ.

## Forwarded Message Assistant

Если пользователь пересылает сообщение боту в личку, private router распознаёт forwarded metadata и сохраняет текст как context item в обычную chat memory.
После этого бот предлагает команды:

- `/summary`
- `/draft_reply`
- `/translate`
- `/factcheck`

Jarvis не делает вид, что видит исходный личный чат: он работает только с пересланным текстом.

## Reply Draft Mode

Если пользователь пишет:

```text
Ответь на это:
<текст клиента>
```

Jarvis вызывает LLM и возвращает черновик ответа.
Это не отправка от имени пользователя; пользователь сам копирует черновик и отправляет его в нужный чат.

## Поток групп

Бот отвечает только если его явно упомянули через `@bot_username` или сообщение является reply на сообщение бота.
Если `GROUP_ASSISTANT_ENABLED=false`, group router молчит.
Для отвечаемого group message router сохраняет сообщение в regular memory группы и ставит arq job `process_llm_message` с `private=false`.
Router не отправляет отдельный accepted message в группу: один provisional принадлежит worker, чтобы его можно было отредактировать в финальный ответ.
Если `STREAMING_GROUP_FALLBACK_ENABLED=true`, worker не использует `sendMessageDraft`, отправляет `sendChatAction typing`, provisional `Принял. Готовлю групповой ответ.`, throttled `editMessageText` и финальный edit. Если edit failed, worker отправляет fallback final `sendMessage` ровно один раз.
Group fallback finalization защищена `final_delivered`: повторный вызов не отправляет второй финальный ответ, а Telegram `message is not modified` считается safe no-op/success.
Если group fallback выключен, worker использует старый final-only path.
Обычные group messages без mention/reply должны игнорироваться без записи в regular memory и без LLM job.
Сообщения от неразрешённых пользователей в group/supergroup молча отсекаются middleware; в private chat middleware по-прежнему отвечает `Доступ запрещён.`
Если privacy mode Telegram ограничивает updates или Telegram присылает `guest_message` вместо обычного `message`, Jarvis не обещает чтение всей истории группы, а такой вызов не считается Group Assistant.

## Production webhook ingress

Production Telegram ingress остаётся `POST /telegram/webhook`; router подключается в `app/main.py` через `routes_telegram.router`, а setup script формирует URL как `<PUBLIC_BASE_URL>/telegram/webhook`.
Polling readiness и polling runner могут удалять webhook только для local/Mac polling smoke. При `APP_ENV=production` они не выполняют `deleteWebhook`, чтобы production webhook не замолчал после диагностического smoke.

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
Streaming использует SSE `chat/completions` (`stream=true`) через тот же OpenAI-compatible adapter. Если streaming provider path ломается, worker пробует обычный non-stream completion и отправляет финальный ответ без draft/edit preview.

Stage 4D добавляет runtime provider override через PostgreSQL runtime setting `active_llm_provider` в таблице `runtime_settings`.

- `auto` — старое поведение через `LLM_PRIMARY_PROVIDER` и `LLM_FALLBACK_PROVIDER`.
- `yandex` — worker использует Yandex provider напрямую.
- `openrouter` — worker использует OpenRouter provider напрямую.

Worker читает setting при обработке каждого `process_llm_message`, поэтому переключение применяется к следующим сообщениям и не требует изменения `.env` или Railway Variables. Если setting отсутствует или повреждён, используется `auto`.

Telegram UI для настройки находится в `app/bot/routers/commands.py`: `/settings`, кнопка `Настройки`, callback ids `settings:provider:auto`, `settings:provider:yandex`, `settings:provider:openrouter`, `settings:refresh`, `settings:close`. Доступ проверяется по `ADMIN_TELEGRAM_IDS`; callback path имеет отдельную admin-проверку, потому что message middleware не покрывает callback queries.

PostgreSQL доступ к setting изолирован в `app/db/repositories/runtime_settings.py`, бизнес-валидация значений — в `app/services/runtime_settings_service.py`.

## Streaming

`StreamBuffer` не даёт отправлять обновление на каждый токен. Flush происходит по одному из условий:

- прошло не меньше `STREAMING_DRAFT_UPDATE_INTERVAL_MS` или `STREAMING_GROUP_EDIT_INTERVAL_MS`;
- накопилось не меньше `STREAMING_MIN_CHARS_DELTA` символов после последнего flush;
- найден конец предложения;
- stream завершён.

Private draft не считается постоянным сообщением и не пишется в БД. В БД пишется только финальный assistant response после `sendMessage` или финального group edit/send.
Guest Mode не использует streaming. Business Mode не включает auto-reply в Stage 3A-S, но fallback abstraction учитывает `business_connection_id` для `sendChatAction`.

Telegram text limits:

- draft/edit preview обрезается до Telegram-safe длины;
- финальный ответ делится на Telegram-safe chunks при отправке;
- в PostgreSQL сохраняется один полный assistant response, а не отдельные chunks.

## Business Mode / Secretary Foundation

Business Mode — optional integration, а не основной путь для обычного аккаунта.
Он требует Telegram Business / Secretary connection, `business_connection`, прав `can_reply` и отправки через `business_connection_id`.

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
