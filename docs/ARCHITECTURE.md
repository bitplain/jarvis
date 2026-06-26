# Архитектура Jarvis

## Компоненты

- `api` — FastAPI приложение с health, ready, Telegram webhook и admin diagnostics.
- `worker` — arq worker, который выполняет LLM generation jobs и scheduled reminder delivery.
- `postgres` — хранилище пользователей, чатов, сообщений, LLM-запросов, списков покупок, напоминаний и stub-событий.
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
3. Middleware пропускает env admin из `ADMIN_TELEGRAM_IDS` или пользователя из PostgreSQL allowlist.
4. Private handler сохраняет входящее сообщение в PostgreSQL.
5. Handler ставит arq job `process_llm_message`.
6. Worker собирает system prompt и последние `MEMORY_MAX_MESSAGES`.
7. Worker вызывает LLM provider через streaming interface, если `STREAMING_ENABLED=true`.
8. В private chat worker пробует Telegram `sendMessageDraft` с non-zero `draft_id`.
9. Если включён `TELEGRAM_PRIVATE_DRAFT_STREAMING_ENABLED=true`, worker сначала пробует `sendRichMessageDraft` с rich thinking block `Думаю`, затем обновляет тот же `draft_id` обычным text draft.
10. `StreamBuffer` обновляет draft не на каждый token, а по интервалу, приросту текста, границе предложения или финалу.
11. Если draft API недоступен, текущий job переключается на fallback sink.
12. После генерации worker отправляет финальный `sendMessage` и сохраняет только финальный ответ.

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
Если `STREAMING_GROUP_FALLBACK_ENABLED=true`, worker не использует `sendMessageDraft`, отправляет `sendChatAction typing`, provisional `Думаю`, throttled `editMessageText` и финальный edit. Если edit failed, worker отправляет fallback final `sendMessage` ровно один раз.
Group fallback finalization защищена `final_delivered`: повторный вызов не отправляет второй финальный ответ, а Telegram `message is not modified` считается safe no-op/success.
Если group fallback выключен, worker использует старый final-only path.
Обычные group messages без mention/reply должны игнорироваться без записи в regular memory и без LLM job.
Сообщения от неразрешённых пользователей в group/supergroup молча отсекаются middleware; в private chat middleware по-прежнему отвечает `Доступ запрещён.`
Если privacy mode Telegram ограничивает updates или Telegram присылает `guest_message` вместо обычного `message`, Jarvis не обещает чтение всей истории группы, а такой вызов не считается Group Assistant.

## Списки покупок и напоминания

Stage 4G добавляет только явные команды пользователя. Router `app/bot/routers/lists_reminders.py` подключён до generic private/group LLM handlers, поэтому clear intent не создаёт `process_llm_message`, а обычный разговор продолжает идти в LLM.

Shopping list commands поддерживают добавление, показ списка, удаление exact active item и очистку купленного. Private list scoped как `scope_type=private`, `scope_chat_id=user_id`, `owner_user_id=user_id`; group list scoped как `scope_type=group`, `scope_chat_id=group_chat_id`, `owner_user_id=null`.

Shopping item parser живёт в `app/services/simple_intent_parser.py` и остаётся deterministic. Add payload сначала проходит `sanitize_shopping_items_input`: текущий bot mention (`@Home_ai_my_bot` в любом регистре) вырезается, произвольные чужие mentions не трогаются, пробелы схлопываются. Затем `split_shopping_items` делит позиции по запятой, точке с запятой, newline и простому русскому connector `и` между словами. Поэтому `мазик и молоко` сохраняется двумя item-ами, а `@Home_ai_my_bot творожок` сохраняется как `творожок`. Strong colon triggers `купить:`, `покупки:` и `список покупок:` используют `split_shopping_colon_items`: существующие разделители работают как раньше, а plain payload из 2-10 простых слов делится по пробелам (`Купить: хлеб сок молоко` -> три item-а). Вопросы `где купить молоко?`, `можешь купить молоко?` и `что купить?` не становятся add intent. Те же helpers используются в private/group intent path и shopping add FSM.

Reminder commands поддерживают простые deterministic patterns: `через N минут/часов`, `сегодня/завтра в HH[:MM]`, `DD.MM в HH[:MM]`. Timezone по умолчанию — `Europe/Moscow`; Stage 4G-1 хранит user-facing timezone в `runtime_settings` ключом `lists.timezone`, валидирует его через `zoneinfo.ZoneInfo` и применяет к parsing/display. В PostgreSQL reminder time сохраняется UTC.

PostgreSQL таблицы:

- `shopping_lists`
- `shopping_list_items`
- `reminders`

Telegram UI использует обычные сообщения, FSM input и inline buttons. Ответы форматируются Telegram HTML с обязательным escaping пользовательского текста через `html.escape`; raw MarkdownV2 не используется. Callback data короткие: `shop:*`, `rem:*`, `settings:lists:*`; пользовательский текст в callback data не кладётся. Повторные clicks и уже изменённые entities обрабатываются как безопасные no-op/update.

`/settings -> Списки и напоминания` остаётся частью admin-only settings UI. Раздел показывает текущий timezone, help, личный список покупок и active reminders. Add-flow для shopping/reminder живёт в `app/bot/routers/lists_reminders.py` как FSM state, подключён до generic LLM handlers и не создаёт `process_llm_message`.

Worker delivery реализован в `deliver_due_reminders` через существующий arq worker и cron tick каждые 30 секунд. Worker берёт due scheduled reminders, форматирует display time через `lists.timezone`, отправляет HTML message через Telegram и помечает reminder `sent` только после успешной отправки. При send failure запись остаётся retryable scheduled после rollback.

Stage 4G/4G-1 не включает watcher, авто-чтение всех сообщений, Telegram Business checklists, native Telegram reminders, voice/transcription и LLM parsing списков/напоминаний.

## Status diagnostics и household context

Stage 4I делает `/status` admin-only диагностикой runtime вместо списка feature flags.
Router остаётся в `app/bot/routers/commands.py`, а сбор проверок вынесен в `app/services/status_service.py`.

`/status` проверяет:

- API process локально;
- PostgreSQL через `SELECT 1`;
- Redis через `PING`;
- arq worker freshness через Redis key `jarvis:worker:heartbeat`;
- webhook configured/unknown по безопасной config/self-healing модели, без destructive Telegram calls;
- due reminders count без текста напоминаний;
- active LLM provider из `runtime_settings`;
- draft streaming env flags;
- prompt profiles и access DB availability.

Heartbeat обновляется worker jobs `process_llm_message` и `deliver_due_reminders`. Если Redis недоступен, heartbeat не ломает job и `/status` показывает degraded/unknown.

Household context foundation реализован отдельным router `app/bot/routers/household_memory.py`, подключённым после списков/напоминаний и до generic private/group LLM handlers. Поэтому явные memory-команды не создают `process_llm_message`, а обычный private text продолжает идти в LLM.

Поддержанные intent forms:

- `запомни: <факт>`;
- `запомни что <факт>`;
- `что ты помнишь?`;
- `забудь: <текст>`;
- `забудь 1`;
- `забудь #1`;
- `удали память 1`.

List UX всегда показывает нумерованный список и inline-кнопки `🗑 N` / `➕ Запомнить`. Delete by number удаляет запись с этим номером только в текущем scope. Delete by text использует нормализованное fuzzy/contains matching: case-insensitive, `ё -> е`, без пунктуации, с удалением слабых слов delete-query (`что`, `это`, `про`, connector `и`) и token-overlap fallback. Если найден один кандидат, он soft-delete-ится и больше не попадает в LLM injection. Если кандидатов несколько, router показывает выбор с кнопками и не удаляет автоматически. Если совпадений нет, пользователь получает подсказку открыть `что ты помнишь?` и удалить по номеру.

Private memory scoped как `scope_type=private`, `scope_chat_id=user_id`. Group memory scoped как `scope_type=group`, `scope_chat_id=group_chat_id` и доступна только через mention/reply по текущей access policy. Обычные group messages без trigger не используются для памяти.

Callback-delete (`mem:*`) повторно проверяет access policy и перед удалением сверяет memory id с active entries текущего private/group scope. Crafted или устаревший callback из другого scope не должен удалять чужую запись.

PostgreSQL таблица `household_memory_entries` хранит soft-deletable записи: `id`, `scope_type`, `scope_chat_id`, `created_by_user_id`, `text`, `status`, timestamps. Active limit: 100 entries per scope, text limit: 500 chars. Secret-looking text отклоняется до записи в БД.

LLM injection происходит в `MemoryService.build_context`: active memories текущего scope добавляются в system prompt как короткий блок `Память о текущем чате`, максимум 20 записей / 2000 символов. При DB error worker пишет sanitized `household_memory_prompt_unavailable` и продолжает обычный LLM ответ без memory block. Deleted memories и memories других чатов не подмешиваются.

Stage 4I не включает watcher, auto-memory, чтение всей истории группы, voice/media/transcription, Telegram Business integration или изменения Railway Variables.

## Access Settings

Stage 4F-1 хранит разрешённых пользователей и группы в PostgreSQL таблице `telegram_access_entries`.

Поля таблицы: `entry_type` (`user` или `group`), `telegram_id` bigint, optional `label`, optional `created_by`, timestamps. Уникальность задаётся по `(entry_type, telegram_id)`.

`ADMIN_TELEGRAM_IDS` остаются env-based super admins: они всегда allowed и только они могут управлять `/settings`. Записи в `telegram_access_entries` дают доступ к боту, но не дают права администратора.

`/whoami` доступен всем и показывает только ID текущего пользователя, тип текущего чата и ID текущего чата. В group/supergroup он дополнительно показывает, разрешены ли именно текущий user и текущая group. Списки admin/allowed users не раскрываются.

Group allowlist mode включается только после добавления первой разрешённой группы. Пока список групп пустой, authorized user mention/reply в любой группе работает как раньше. Когда группы добавлены, для group ответа нужны и allowed user, и allowed group.

Telegram UI находится в `app/bot/routers/commands.py`: `/settings -> Доступ`, callback ids `settings:access:*`, FSM states `TelegramAccessInput.*`. Доступ к таблице изолирован в `app/db/repositories/telegram_access.py`, правила доступа — в `app/services/telegram_access_service.py`. Middleware пишет sanitized `telegram_access_decision` без текста сообщений, labels, токенов, headers, prompts и полного Telegram update.

Access input FSM принимает один ID с label или несколько IDs через пробел/строки. Для webhook runtime callback update и следующий text message должны проходить через один persistent aiogram Dispatcher на `app.state`: FSM storage живёт внутри Dispatcher, поэтому transient Dispatcher per update ломает access input и отдаёт текст generic private LLM handler.

## Production webhook ingress

Production Telegram ingress остаётся `POST /telegram/webhook`; router подключается в `app/main.py` через `routes_telegram.router`, а setup script формирует URL как `<PUBLIC_BASE_URL>/telegram/webhook`.
При `APP_ENV=production` API startup после startup migrations выполняет Telegram webhook self-healing setup через общую sanitized logic `app.services.telegram_webhook_setup`. Это восстанавливает state Telegram webhook после deploy, если ранее он был удалён, но не делает live Telegram calls в dev/test и не запускается в worker.
Если `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET` или `PUBLIC_BASE_URL` отсутствуют, либо Telegram API временно недоступен, API startup не падает: пишется sanitized `telegram_webhook_setup_failed` с `webhook_host` и `webhook_path`, без token/secret/header.
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

Stage 4F-2 hotfix использует ту же таблицу `runtime_settings` для raw prompt editor:

- `prompt.private` — system prompt для private chat worker jobs;
- `prompt.group` — system prompt для group/supergroup mention/reply worker jobs;
- `prompt.watch` — заготовка для будущего watcher, в текущем runtime автоматически не используется.

`/settings -> Промты` показывает default/custom source, длину и текущий prompt text. Custom prompt сохраняется только admin user, лимит — 4000 символов. Prompt edit FSM перехватывает следующий private text до generic private LLM handler, поэтому сообщение с новым prompt не уходит в `process_llm_message` и не получает `Думаю`. Длинный prompt в UI рендерится как safe preview; полный текст отправляется отдельным plain-text сообщением без `parse_mode`.

Старые enum-пресеты `prompt_profile_private`, `prompt_profile_group`, `prompt_profile_watcher` остаются отдельным разделом `Стиль ответа`. Они не являются raw prompt editor и не заменяют ключи `prompt.private`, `prompt.group`, `prompt.watch`.

## Streaming

`StreamBuffer` не даёт отправлять обновление на каждый токен. Flush происходит по одному из условий:

- прошло не меньше `STREAMING_DRAFT_UPDATE_INTERVAL_MS` или `STREAMING_GROUP_EDIT_INTERVAL_MS`;
- накопилось не меньше `STREAMING_MIN_CHARS_DELTA` символов после последнего flush;
- найден конец предложения;
- stream завершён.

Private draft не считается постоянным сообщением и не пишется в БД. В БД пишется только финальный assistant response после `sendMessage` или финального group edit/send.
Guest Mode не использует streaming. Business Mode не включает auto-reply в Stage 3A-S, но fallback abstraction учитывает `business_connection_id` для `sendChatAction`.

Stage 4F-3 добавляет Mira-style private streaming через официальный Telegram draft/rich draft API. Новый режим включается отдельно через `TELEGRAM_PRIVATE_DRAFT_STREAMING_ENABLED=true`: private chat получает rich thinking draft `Думаю`, а последующие chunks обновляют тот же `draft_id`. Если rich draft недоступен, job возвращается к text draft `Думаю`; если text draft тоже падает, worker использует fallback с тем же `Думаю`. Group/supergroup path не использует `sendMessageDraft` или `sendRichMessageDraft`, потому что draft methods предназначены для private chat.

Stage 4F-4 упрощает ожидание ответа до единого `Думаю`. В Mira private path webhook не отправляет отдельное обычное сообщение, чтобы не дублировать draft thinking. В private path без Mira webhook может отправить короткое `Думаю`; в group/supergroup это обычное provisional message, которое worker затем редактирует или заменяет финальным ответом. `/start`, `/settings`, `/whoami`, access FSM и prompt FSM не используют thinking/provisional text.

Визуальный эффект посимвольного роста полностью не управляется backend: Jarvis отправляет throttled draft updates, а Telegram client сам анимирует изменение draft preview.

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
