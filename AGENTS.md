# Правила проекта Jarvis

## Язык и стиль

- Вся документация, stage-отчёты, комментарии к задачам и ответы бота пользователю пишутся на русском языке.
- Пользовательские ответы Telegram-бота должны быть только на русском.
- Если бот не знает ответ, он честно говорит, что не знает, и не выдумывает факты.

## Безопасность

- Нельзя хардкодить Telegram token, LLM API keys, пароли, model IDs, Telegram IDs и другие секреты.
- Все секреты задаются только через `.env` или GitHub Secrets.
- `.env` не должен попадать в git.
- В логах нельзя печатать Telegram token, LLM API keys, Authorization headers, пароли и реальные env secrets.

## Stage 1 границы

- GitHub repository не создаётся и ничего не пушится до отдельной команды.
- Secretary Mode и Mini App в Stage 1/2 не реализуются полностью.
- Business/Secretary код должен оставаться явным stub/no-op или выбрасывать `NotImplementedError`, чтобы его нельзя было принять за готовую функцию.
- Реальный Telegram/LLM smoke без настоящих env-секретов считается `BLOCKED_NEEDS_REAL_ENV`, а не успехом.
- Stage 1R env bootstrap может генерировать только локальные секреты в `.env`, выводить только sanitized status и никогда не коммитить реальные значения `.env`.

## Stage 2 Guest Mode

- Guest Mode обрабатывает только Telegram update type `guest_message`.
- Ответ Guest Mode отправляется только финальным `answerGuestQuery`.
- В Guest Mode запрещены streaming, `sendMessageDraft`, обычная chat memory и постоянная память чужого guest-чата.
- Если `guest_query_id` отсутствует, бот не отвечает и сохраняет только диагностическое событие.
- По умолчанию `GUEST_MODE_ENABLED=false` и `GUEST_MODE_ADMIN_ONLY=true`.
- Если Telegram не передал caller user id, Guest Mode отвечает отказом владельца и не вызывает LLM.
- Guest Mode учитывает только текст guest-вызова и replied message, если Telegram его передал.
- Обычный private/group бот остаётся доступен только `ADMIN_TELEGRAM_IDS`.
- Обычное сообщение в личке или группе не считается Guest Mode smoke.

## Stage 2R Polling Smoke

- Для локального Mac real smoke без публичного HTTPS URL используется polling через `scripts/run_polling.py`.
- Перед polling webhook обязательно удаляется через Telegram `deleteWebhook`.
- `drop_pending_updates` по умолчанию должен быть `false`; включать drop можно только явным флагом `--drop-pending-updates`.
- Readiness script `scripts/smoke_polling_readiness.py` не должен вызывать `getUpdates`, чтобы не съесть ручной `guest_message`.
- Polling smoke не использует tunnel и не засчитывает обычные `message`/group mention updates как Guest Mode.

## Stage 3A Business Mode

- Business Mode по умолчанию выключен: `BUSINESS_MODE_ENABLED=false`.
- Ответы от имени Telegram Business account по умолчанию запрещены: `BUSINESS_REPLY_ENABLED=false`.
- Stage 3A не включает постоянный autonomous auto-reply и не отвечает всем входящим business-сообщениям.
- Ручной test reply разрешён только при `BUSINESS_MODE_ENABLED=true`, `BUSINESS_REPLY_ENABLED=true`, `BUSINESS_ADMIN_ONLY=true`, owner из `ADMIN_TELEGRAM_IDS`, активном connection, `can_reply=true` и trigger `BUSINESS_REPLY_TRIGGER`.
- Business Mode не использует обычную chat memory и Guest Mode memory; используется отдельная business-memory по `business_connection_id + chat_id`.
- В отчётах и логах нельзя выводить полный `business_connection_id`, Telegram IDs и приватный текст business-сообщений.
- Readiness script `scripts/smoke_business_readiness.py` не должен вызывать `getUpdates`, чтобы не съесть ручные business updates до polling runner.
- Real Business Mode smoke засчитывается только если пришли настоящие `business_connection` и `business_message`, ответ отправлен через `business_connection_id`, а БД подтвердила записи.

## Stage 3A-R Regular Assistant Mode

- Regular Assistant Mode — основной путь для обычного Telegram-аккаунта.
- Он работает через private chat с ботом, group mode при добавлении бота в группу, Guest Mode через `@bot_username`, forwarded-message assistant и draft reply assistant.
- Bot API не может читать личные входящие сообщения обычного пользователя и не может отвечать от имени обычного пользователя без Telegram Business / Secretary connection.
- Business / Secretary Mode остаётся optional advanced mode: требует Telegram Business / Secretary connection, `business_connection`, `can_reply` и отправку через `business_connection_id`.
- Нельзя писать в документации или ответах, что Secretary Mode работает без Business account.
- Draft Reply Mode возвращает только черновик, который пользователь сам копирует и отправляет.
- Forwarded Message Assistant работает только с текстом, который пользователь явно переслал боту.
- Group Assistant отвечает только на mention или reply на сообщение бота; не обещать чтение всей истории группы.
- Readiness script `scripts/smoke_regular_readiness.py` не требует Business account и должен считать Business Mode optional/disabled нормальным состоянием.

## Stage 3A-R-LIVE Regular Assistant Smoke

- Live smoke для group assistant засчитывается только в настоящей Telegram group/supergroup, где бот добавлен участником.
- Вызов `@bot_username` в чужом чате, который приходит как Telegram `guest_message`, относится к Guest Mode и не засчитывается как group assistant smoke.
- Group plain message без mention/reply должен быть проигнорирован без LLM job и без записи в regular memory.
- Group mention/reply smoke должен подтверждаться обычным `message` update, записью regular memory и worker job `process_llm_message(private=false)`.
- Если BotFather Privacy Mode не доставляет обычный group mention в Bot API, mention smoke считается blocked до отключения privacy mode или другой настройки доставки updates; это нельзя засчитывать как PASS.
- Команды `/summary`, `/draft_reply`, `/translate`, `/factcheck` должны принимать inline-аргумент после команды, включая форму `/command@bot_username`, а при пустом аргументе использовать доступный сохранённый контекст или честно просить контекст.

## Stage 3A-R-GROUP Routing

- Для runtime group mention matching фактический username из Telegram `get_me()` важнее `TELEGRAM_BOT_USERNAME` из `.env`, потому что локальный env может быть stale.
- Group diagnostics в логах должны быть sanitized: masked chat/user ids, chat type, message id, classification, matched username, should_process и enqueue status; полный текст group-сообщений не логируется.
- `/command@other_bot` должен игнорироваться.
- Сообщение, состоящее только из `@bot_username`, должно отвечать коротко: `Напиши запрос после упоминания бота.`
- `scripts/smoke_group_readiness.py` не должен вызывать `getUpdates` и не должен съедать ручные group updates.

## Stage 3A-S Streaming UX

- Release-hardening запрещён, пока Stage 3A-S не получил отдельный verified verdict.
- Streaming включается только через env flags: `STREAMING_ENABLED`, `STREAMING_PRIVATE_DRAFT_ENABLED`, `STREAMING_GROUP_FALLBACK_ENABLED`.
- Private chat path использует Telegram `sendMessageDraft` с non-zero `draft_id`, throttled `StreamBuffer`, затем финальный `sendMessage`.
- Draft preview не считается постоянным сообщением; в БД сохраняется только финальный assistant response.
- Если draft API недоступен или падает, текущий job должен перейти на sanitized fallback без вывода token/key/header.
- Group/supergroup path не использует `sendMessageDraft`; fallback использует `sendChatAction typing`, один worker-owned provisional `Думаю`, throttled `editMessageText` и финальный edit/send.
- Unauthorized group/supergroup messages, включая mention/reply от неразрешённого пользователя, должны молча игнорироваться без ответа `Доступ запрещён`; private unauthorized всё ещё получает `Доступ запрещён.`
- Group fallback finalization должна быть idempotent: после успешного final edit, safe `message is not modified` или fallback final send повторный вызов ничего не отправляет и логирует sanitized `telegram_group_final_already_delivered`.
- Telegram `message is not modified` в group final edit считается safe no-op/success и не должен запускать fallback duplicate send.
- Guest Mode остаётся final-only: `guest_message -> LLM final answer -> answerGuestQuery`, без streaming, draft и group edit sink.
- Business / Secretary auto-reply в Stage 3A-S не включается; разрешена только fallback abstraction с учётом `business_connection_id` для `sendChatAction`.
- Draft/edit preview должен учитывать Telegram text limit; финальный ответ можно делить на Telegram-safe chunks, но в БД должен сохраняться один полный assistant response.
- Readiness script `scripts/smoke_streaming_readiness.py` не должен вызывать `getUpdates` и не должен съедать ручные private/group/guest updates.
- Live smoke Stage 3A-S засчитывается только по фактическим Telegram/logs/DB evidence; нельзя писать “должно работать”.

## Stage 4B Railway Deploy Prep

- Railway production model использует отдельный service для API/webhook, отдельный service для worker, Railway PostgreSQL и Railway Redis.
- Railway не запускает `docker-compose.yml` как единый production stack; compose остаётся локальным development/smoke flow.
- Production API должен слушать порт из Railway `$PORT`; локальный compose flow остаётся на `8000`.
- Production runtime использует webhook mode. Polling разрешён только для local/Mac smoke и не должен работать параллельно с production webhook runtime.
- Polling readiness и polling runner не должны выполнять `deleteWebhook` при `APP_ENV=production`; production webhook можно менять только явным setup script/операторским действием.
- Railway variables задаются через Railway UI/CLI; `.env`, Telegram token, LLM keys, `ADMIN_API_TOKEN`, Authorization headers и полные `ADMIN_TELEGRAM_IDS` не коммитятся и не печатаются.
- Stage Ops-1 фиксирует текущую production deployment strategy: production deploys only from GitHub main; API healthcheck endpoint: /health; /ready is diagnostics/readiness для Postgres/Redis; Database migrations run via app startup migrations; Railway preDeploy migration command is intentionally not used; Worker does not run migrations.
- Railway UI для `jarvis-api` должен быть синхронизирован вручную: Healthcheck path: /health; Start command: `uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}`; Pre-deploy command: empty; Deploy source: GitHub main.
- Railway UI для `jarvis-worker` должен быть синхронизирован вручную: Start command: `arq app.workers.arq_settings.WorkerSettings`; Pre-deploy command: empty; Deploy source: GitHub main.
- Если `/ready` используется как Railway healthcheck, deploy может падать при transient Postgres/Redis issues; поэтому `/health` предпочтителен для platform healthcheck, а `/ready` остаётся diagnostics/readiness endpoint.
- Webhook на Railway устанавливается через sanitized script `scripts/setup_telegram_webhook.py` или совместимый `scripts/set_telegram_webhook.py`; scripts должны читать Railway process env и не печатать token/secret.
- API startup при `APP_ENV=production` выполняет Telegram webhook self-healing setup после startup migrations, использует тот же sanitized setup logic и логирует только `telegram_webhook_setup_started`, `telegram_webhook_setup_completed`, `telegram_webhook_setup_failed`, `webhook_host`, `webhook_path`.
- Webhook self-healing не запускается в worker, dev и test. Отсутствующий token/public URL/secret или временная ошибка Telegram API не должны валить API startup; нужно логировать sanitized failure без token/secret/header.
- Railway project/deploy/push/tag/release не создаются без отдельной команды.

## Telegram Update Idempotency

- Production webhook route должен быть идемпотентен по Telegram `update_id`: повторный delivery одного update возвращает `200 OK` и не вызывает aiogram Dispatcher второй раз.
- Dedup guard использует Redis key `telegram:update:<update_id>` через `SET NX` с коротким TTL; при Redis error guard fail-open логирует sanitized `telegram_webhook_dedup_unavailable` и продолжает обработку, чтобы не ломать `/start` и settings callbacks.
- Duplicate skip логируется sanitized событием `telegram_webhook_duplicate_update_skipped` с `update_id`, `message_id`, chat type и masked chat/user ids; полный текст сообщения, token, secret, Authorization headers и полный update не логируются.
- Private/group LLM enqueue должен передавать стабильный arq `_job_id=llm:<chat_id>:<message_id>`, чтобы повторная доставка одного Telegram message не создавала несколько `process_llm_message`.
- Readiness script `scripts/smoke_telegram_update_idempotency_readiness.py` не должен вызывать Telegram API, `getUpdates`, `setWebhook` или `deleteWebhook`.

## Stage 4D Provider Settings

- Активный LLM-агент переключается только через PostgreSQL runtime setting `active_llm_provider`, а не через изменение `.env` или Railway Variables.
- Допустимые значения: `auto`, `yandex`, `openrouter`; отсутствие записи означает `auto`.
- `auto` сохраняет env-based primary/fallback логику `LLM_PRIMARY_PROVIDER` и `LLM_FALLBACK_PROVIDER`.
- `yandex` и `openrouter` принудительно выбирают соответствующий provider для следующих worker jobs; worker должен читать setting перед обработкой job и не кэшировать выбор навечно.
- Telegram UI `/settings` и callback `settings:*` доступны только admin user из `ADMIN_TELEGRAM_IDS`; non-admin получает `Доступ запрещён.`
- Кнопка `Настройки` может показываться в `/start`, но обработчик всё равно обязан проверять admin access.
- Если выбранный provider не настроен или падает, пользователю показывается безопасная русская ошибка, а logs остаются sanitized без token/key/header/provider response body.
- Railway Variables `YANDEX_*` и `OPENROUTER_*` остаются обязательными для worker, но реальные значения нельзя выводить в Telegram UI, docs, logs или PR.
- API production startup code должен автоматически выполнять `alembic upgrade head` через app startup migrations; Railway start command и preDeploy command миграции не запускают, а ручная миграция не должна быть обязательной для кнопки `Настройки`.
- Production deploy Stage 4D происходит только после PR review, merge в `main`, CI и Railway production autodeploy; PR Environments выключены.

## Stage 4E Railway Migration And Settings Callback Fix

- API production startup должен иметь code-level startup migration guard: даже если Railway UI Start Command переопределит `railway.api.toml`, `APP_ENV=production` обязан запускать `alembic upgrade head` до приёма webhook requests.
- Startup migration guard не запускается при обычных local/unit tests по умолчанию и не должен запускаться в worker path.
- В логах startup migration guard должны быть короткие sanitized события `startup_migrations_started`, `startup_migrations_completed`, `startup_migrations_failed`.
- Если startup migration падает, API startup должен падать, чтобы Railway deploy не стал healthy со старой схемой.
- Settings callbacks должны быть идемпотентными: `settings:refresh`, повторный `settings:provider:*`, `settings:close` и Telegram `message is not modified` не должны давать HTTP 500.
- Другие `TelegramBadRequest` в settings callbacks нельзя считать успехом молча: нужен sanitized log и безопасный callback answer.

## Stage 4F-1 Access Settings

- Telegram allowlist хранится в PostgreSQL таблице `telegram_access_entries`, а не в `.env`.
- `ADMIN_TELEGRAM_IDS` остаются главными env admin, всегда имеют доступ и не переносятся в таблицу автоматически.
- DB allowed user получает доступ к Jarvis, но не становится admin и не может управлять `/settings`.
- `/settings -> Доступ` и callback `settings:access:*` доступны только admin user из `ADMIN_TELEGRAM_IDS`.
- `/whoami` доступен всем и показывает только Telegram user ID, тип чата и chat ID текущего сообщения; в group/supergroup он дополнительно показывает, разрешены ли именно текущий user и текущая group, без раскрытия списков.
- Если список разрешённых групп пустой, authorized user mention/reply в любой группе работает как раньше.
- После добавления хотя бы одной разрешённой группы group response требует allowed user и allowed group.
- Unknown private user получает `Доступ запрещён.`, unknown group/supergroup user молча игнорируется.
- В логах использовать sanitized события `telegram_access_user_added`, `telegram_access_user_removed`, `telegram_access_group_added`, `telegram_access_group_removed`, `telegram_access_denied_private`, `telegram_access_denied_group_silent`, `telegram_access_decision`.
- `telegram_access_decision` допускает только sanitized поля `chat_type`, `chat_id`, `user_id`, `is_admin`, `is_user_allowed`, `has_group_allowlist`, `is_group_allowed`, `is_mention_or_reply`, `decision`, `reason`; текст сообщений, labels, токены, Authorization headers, prompts и полный Telegram update не логируются.
- Access settings FSM input должен перехватывать следующий private text до generic private LLM handler: не должно быть `process_llm_message` и `Думаю` во время add/remove user/group state.
- Webhook runtime должен переиспользовать persistent aiogram Dispatcher на app instance; transient Dispatcher per update ломает FSM MemoryStorage между callback и message.
- Access input поддерживает один ID с label, несколько IDs через пробел и несколько IDs по строкам; `/cancel` очищает state.
- Prompt Profiles, Shopping List, Reminders, Memory и Smart Watcher в Stage 4F-1 не реализуются.

## Stage 4F-2 Prompt Profiles

- `/settings -> Промты` — это raw prompt editor, а не выбор preset-стиля.
- Raw prompts хранятся в PostgreSQL `runtime_settings` ключами `prompt.private`, `prompt.group`, `prompt.watch`.
- Если custom prompt отсутствует, UI показывает default prompt и `Источник: default`; если есть custom prompt, UI показывает custom text и `Источник: custom`.
- Admin user должен видеть текущий prompt text, редактировать/полностью переписывать prompt, сохранять custom prompt и сбрасывать custom prompt к default.
- Custom prompt лимитируется 4000 символами; prompt text не отправляется с `parse_mode`.
- Если prompt не помещается в экран настроек, UI показывает safe preview и кнопку `Показать полностью`; полный prompt отправляется отдельным plain-text сообщением.
- Prompt edit FSM должен перехватывать следующий private text до generic private LLM handler: не должно быть `process_llm_message` и `Думаю` во время редактирования prompt.
- `/cancel` в prompt edit state отменяет ввод, не меняет prompt и возвращает понятный экран/сообщение.
- Private worker jobs используют `prompt.private`; group/supergroup mention/reply jobs используют `prompt.group`.
- `prompt.watch` пока нигде автоматически не используется и не запускает Smart Watcher.
- DB/runtime_settings error при чтении prompt fallback на default prompt без логирования полного prompt text.
- Presets `balanced`, `short`, `deep`, `draft`, `watcher` можно держать только как отдельный раздел `Стиль ответа`; они не считаются выполнением raw Prompt Profiles.
- Старые style presets хранятся отдельно ключами `prompt_profile_private`, `prompt_profile_group`, `prompt_profile_watcher`; отсутствие записи означает `balanced`.
- Synthetic private ingress тесты для `/start`, обычного private text от admin/allowed user и denial unknown user обязательны перед принятием Stage 4F-2.
- Webhook ingress не должен падать до command/private handler из-за временно недоступного Redis; Redis unavailable логируется sanitized, `/start` и другие non-worker handlers продолжают обрабатываться.
- Все profiles сохраняют базовые правила Jarvis: ответы только на русском, честное признание неизвестности и запрет выдумывать факты.
- Guest Mode, Business Mode и streaming sinks не меняются из-за Prompt Profiles.
- Smart Watcher, списки покупок, напоминания, чтение всех сообщений, изменение streaming и эффект Mira в Stage 4F-2 не реализуются.

## Stage 4F-3 Mira-style Private Streaming

- Mira-style draft streaming включается отдельным env flag `TELEGRAM_PRIVATE_DRAFT_STREAMING_ENABLED`; default `false`.
- `STREAMING_ENABLED=true` и `STREAMING_PRIVATE_DRAFT_ENABLED=true` остаются общими условиями private streaming.
- Новый режим работает только в private chat: сначала rich draft thinking `Думаю` через `sendRichMessageDraft`, затем text draft updates того же non-zero `draft_id`.
- Финальный ответ всегда отправляется обычным `sendMessage`; в БД сохраняется только один полный assistant response.
- Если rich draft недоступен или падает, job должен безопасно вернуться к text draft `Думаю`; если text draft тоже падает, используется старый private fallback без падения job.
- Group/supergroup path не использует `sendMessageDraft` и `sendRichMessageDraft`; остаётся текущий `sendChatAction` + provisional/edit/final fallback.
- Guest Mode остаётся final-only через `answerGuestQuery`, без draft/rich draft/streaming.
- В логах нельзя выводить token/key/header, полный Telegram update, приватный текст chunks или provider response body; draft failures логируются sanitized событиями.
- Exact Mira letter-growth не гарантируется backend: Jarvis обновляет один draft, а Telegram client сам анимирует изменение preview.
- Watcher, shopping list, reminders, чтение всех сообщений и Railway Variables в Stage 4F-3 не меняются.

## Stage 4F-4 Thinking Text Cleanup

- Единый текст ожидания ответа — `Думаю`.
- В private chat с Mira draft (`STREAMING_ENABLED=true`, `STREAMING_PRIVATE_DRAFT_ENABLED=true`, `TELEGRAM_PRIVATE_DRAFT_STREAMING_ENABLED=true`) webhook enqueue не отправляет отдельное обычное сообщение; thinking показывается только draft/rich draft path worker.
- В private chat без Mira draft webhook enqueue отправляет обычное короткое `Думаю`, затем worker доставляет финальный ответ один раз.
- Private draft fallback и group fallback используют тот же `Думаю`.
- Group/supergroup fallback показывает `Думаю` как обычное provisional message, которое worker редактирует или заменяет финальным ответом; Mira-style draft animation в group не используется.
- `/start`, `/settings`, `/whoami`, prompt edit FSM и access FSM не должны показывать `Думаю`.
- Старые длинные accepted/provisional тексты не используются в актуальном app/tests/docs, кроме исторических отчётов.
- Watcher, shopping list, reminders, prompt profiles, access settings, webhook self-healing, Railway Variables и PR #5 в Stage 4F-4 не меняются.

## Stage 4G Lists And Reminders

- Списки покупок и напоминания реализуются собственной логикой Jarvis, а не Telegram Business checklists.
- Stage 4G принимает только явные команды/обращения пользователя; watcher, авто-чтение всех сообщений и “бот сам заметил надо купить” не включаются.
- Parser deterministic и ограниченный: shopping add/show/delete/clear_done и reminders `через N минут/часов`, `сегодня/завтра в HH[:MM]`, `DD.MM в HH[:MM]`.
- Shopping item parser делит позиции по запятой, точке с запятой, newline и простому connector `и` между словами; `мазик и молоко` должно сохраняться как два item.
- Shopping item sanitizer вырезает только текущий bot mention из add payload, case-insensitive; `@Home_ai_my_bot творожок` должно сохраняться как `творожок`, а пустой payload после mention не сохраняется и не уходит в LLM.
- Strong shopping colon triggers `купить:`, `покупки:` и `список покупок:` идут в deterministic shopping add, не в LLM. Для colon payload без запятых/`;`/newline/`и` допускается split 2-10 простых слов по пробелам: `Купить: хлеб сок молоко` -> `хлеб`, `сок`, `молоко`. Вопросы вроде `где купить молоко?`, `можешь купить молоко?` и `что купить?` не становятся add intent.
- Ambiguous normal chat должен идти в обычный LLM path; command-like, но непонятное напоминание получает help text и не вызывает LLM.
- Private commands доступны admin или DB allowed user; group commands доступны только mention/reply от allowed user в allowed group по текущей access policy.
- Telegram UI использует messages + inline buttons; пользовательский текст в HTML обязательно escaping через `html.escape`.
- Raw MarkdownV2 не используется для списков/напоминаний; inline button labels plain text.
- Данные хранятся в PostgreSQL таблицах `shopping_lists`, `shopping_list_items`, `reminders`.
- Private shopping scope: `scope_type=private`, `scope_chat_id=user_id`, `owner_user_id=user_id`; group scope: `scope_type=group`, `scope_chat_id=group_chat_id`, `owner_user_id=null`.
- Reminder timezone по умолчанию `Europe/Moscow`, хранение в БД UTC.
- Reminder delivery выполняет arq worker job `deliver_due_reminders`; reminder помечается `sent` только после успешного Telegram send.
- Stage 4G не трогает Railway Variables, Telegram Business integration, watcher, private ingress, access routing, prompt profiles, webhook self-healing, Mira streaming и group fallback dedup.

## Stage 4G-1 Lists And Reminders UX

- `/settings -> Списки и напоминания` доступен только по текущей admin/private policy settings.
- Настройка timezone хранится в PostgreSQL `runtime_settings` ключом `lists.timezone`; default `Europe/Moscow`.
- Timezone валидируется только через `zoneinfo.ZoneInfo`; invalid value отклоняется русским сообщением, `/cancel` не меняет сохранённое значение.
- `lists.timezone` влияет на parsing reminders, отображение reminder list/create и due reminder delivery; `remind_at` в БД остаётся UTC.
- Help-фразы `помощь список`, `помощь напоминания`, `как пользоваться списком`, `как пользоваться напоминаниями` отвечают Telegram HTML help и не создают LLM job.
- Shopping list UI показывает `➕ Добавить`; add FSM перехватывает следующий private/group text, использует общий shopping parser/sanitizer, поддерживает несколько позиций через запятую/точку с запятой/newline/`и` и не отправляет текст в LLM.
- Shopping `🧹 Очистить всё` всегда требует confirmation `[Да, очистить] [Отмена]`; repeated clicks safe.
- Reminder list UI показывает active reminders с кнопками `✅ Выполнено`, `⏰ +10 мин`, `⏰ +1 час`, `🗑 Удалить` и `➕ Добавить напоминание`.
- Reminder add FSM перехватывает следующий text, использует тот же deterministic parser и не отправляет текст в LLM.
- Callback data остаётся коротким (`shop:*`, `rem:*`, `settings:lists:*`) и не содержит пользовательский текст.
- Stage 4G-1 не включает watcher, voice/transcription, Telegram Business integration, Railway Variables changes и PR #5.

## Stage 4I Status And Household Context

- `/status` — admin-only diagnostics, а не публичный список режимов.
- Non-admin private `/status` получает `Доступ запрещён.`, group/supergroup status для non-admin не раскрывает системные данные.
- `/status` показывает только sanitized сведения: API, PostgreSQL, Redis, worker heartbeat, webhook configured/unknown, due reminders count, active provider, draft streaming, prompt profiles, access DB.
- `/status` не выводит Telegram IDs, tokens, API keys, Authorization headers, model secret values, prompt text или private message text.
- Worker heartbeat хранится в Redis key `jarvis:worker:heartbeat`; stale/missing heartbeat считается degraded, но не ломает worker jobs.
- Household context memory работает только по явным командам `запомни:`, `запомни что`, `что ты помнишь?`, `забудь:`, `забудь 1`, `забудь #1`, `удали память 1`.
- `что ты помнишь?` показывает нумерованный список; удаление поддерживает номер текущего списка и нормализованный fuzzy/contains match по тексту.
- Если delete по тексту находит несколько похожих записей, бот показывает выбор с кнопками и не удаляет автоматически; если совпадений нет, бот предлагает открыть список и удалить по номеру.
- В group/supergroup memory-команды работают только через mention/reply по текущей access policy; обычные group messages без trigger игнорируются и не читаются ради памяти.
- Memory callbacks (`mem:*`) должны отдельно проверять текущую access policy, потому что message middleware не покрывает callback queries, и удалять только записи текущего private/group scope.
- Memory хранится в PostgreSQL `household_memory_entries`, scoped отдельно для `private` user chat и `group` chat.
- Memory text limit: 500 chars; active limit: 100 entries per scope; delete is soft-delete.
- Secret-looking memory text (`token`, `password`, `api key`, `Authorization`) должен отклоняться сообщением `Похоже на секрет. Я не буду это сохранять.`
- В Telegram HTML выводе memory text обязательно escaping через `html.escape`.
- Active scoped memory можно inject в LLM system prompt коротким блоком `Память о текущем чате`, максимум 20 записей / 2000 символов.
- DB error при memory injection не должен ломать LLM answer; нужно sanitized log без текста памяти.
- Household memory не используется для access decisions и не смешивается между private/group/другими chat ids.
- Stage 4I не включает watcher, auto-memory, чтение всех сообщений, voice/transcription/media, Telegram Business integration, Railway Variables changes и live destructive Telegram calls.

## Stage 4J Daily Brief + Shopping v2

- Stage 4J добавляет Daily Brief / `Сводка дня` и Shopping v2 без watcher, voice/transcription/media, Telegram Business и auto-reading group messages.
- Daily Brief запускается только явными командами `сводка`, `сводка дня`, `что сегодня?` или scheduled private auto-brief.
- Private brief показывает текущий private scope: сегодняшние напоминания, просроченные напоминания, активные покупки и capped household memory.
- Group/supergroup brief работает только по mention/reply и только по текущему group scope; group auto-brief в Stage 4J не отправляется.
- `/settings -> Сводка дня` доступен только admin/private settings policy и управляет private auto-brief: enabled, `send_time` в формате `HH:MM`, timezone IANA и `Показать сейчас`.
- Daily brief settings хранятся в PostgreSQL таблице `daily_brief_settings`; `last_sent_date` хранит локальную дату последней успешной отправки.
- Worker job `deliver_daily_briefs` запускается arq cron раз в минуту, отправляет brief только если local `HH:MM` совпал и `last_sent_date` не равен сегодняшней local date.
- Если daily brief Telegram send падает, job логирует sanitized `daily_brief_send_failed` без текста brief/secrets и не обновляет `last_sent_date`.
- Shopping v2 расширяет `shopping_list_items` nullable-полями `quantity`, `unit`, `note`, `category`; старые rows без этих полей должны отображаться и работать как раньше.
- Shopping parser остаётся deterministic и без LLM: `2 шт`, `1 кг`, `500 г`, `2 бутылки` идут в quantity/unit; `размер 4`, проценты и скобки идут в note.
- Простые категории: `Молочка`, `Хлеб`, `Ребёнок`, `Мясо`, `Овощи`, `Фрукты`; если правило не сработало, используется `Другое`.
- Shopping list display группирует active items по категориям, но старые items без v2 fields отображаются нормально; весь пользовательский текст в HTML обязательно escaping через `html.escape`.
- Stage 4J не меняет Railway Variables, Prompt Profiles, access routing, Mira/private streaming, Guest Mode, Business Mode, `/status`, reminder delivery semantics и logging redaction.

## Stage 4K Provider-agnostic Web Search

- Web Search — отдельный инструмент Jarvis, а не прямой интернет-доступ LLM provider-а.
- Поиск запускается только явными командами: `найди ...`, `поищи ...`, `проверь в интернете ...`, `посмотри в интернете ...`, `что нового по ...`, `найди актуальную информацию ...`.
- Явные current-info/weather фразы тоже считаются web search intent: `покажи погоду в Москве`, `погода в Москве сегодня`, `какая погода в Москве сейчас`, `покажи курс доллара`, `покажи новости про Telegram`.
- Auto-search на обычные вопросы запрещён; обычный `Привет` и вопросы без explicit search trigger идут в normal LLM path.
- Group/supergroup search работает только через mention/reply по текущей access policy; обычные group non-mention сообщения игнорируются как раньше.
- Vague explicit search может создавать Redis pending clarification на 10 минут по scope private `chat+user` или group `chat+user`; `/cancel` очищает pending clarification. Redis unavailable не должен ломать обычный routing.
- Search providers: `disabled`, `tavily`, `brave`; ключи только через env/Railway Variables `TAVILY_API_KEY`, `BRAVE_SEARCH_API_KEY`, значения не печатать.
- Runtime settings: `web_search.enabled`, `web_search.provider`, `web_search.max_results`; `/settings -> Интернет-поиск` admin-only.
- Если поиск выключен, отвечать `Интернет-поиск выключен. Включите его в /settings -> Интернет-поиск.`
- Если provider `disabled` или key отсутствует при включённом поиске, `/settings -> Интернет-поиск` показывает `Статус: не настроен`, а поиск отвечает `Интернет-поиск не настроен: выберите provider и добавьте API key.`
- Search context строится snippets-only из provider results; page fetching, browser automation, выполнение кода со страниц, scraping private/auth/paywalled pages и обход login/paywall запрещены.
- URL safety обязан отбрасывать localhost, loopback, private RFC1918 ranges, link-local, metadata IP `169.254.169.254`, non-http/https schemes и пустые hosts.
- Финальный ответ должен быть на русском и включать deterministic список источников; если источников недостаточно, Jarvis честно говорит об этом.
- Финальный Telegram web-search ответ не должен показывать raw Markdown markers (`**`, `__`, `[title](url)`); provider/model text должен быть escaped, links только safe http/https, Telegram HTML parse error должен иметь один plain fallback.
- Cache хранится в PostgreSQL `web_search_cache` по `(provider, query_hash)`; provider error не cache-ится.
- Логи не должны содержать full query text, API keys, Authorization headers, provider response body, prompts или private message text; допустимы provider, query length, result count, status и sanitized ids.
- Stage 4K не включает watcher, voice/media, Telegram Business, Railway Variables changes, auto-reading group messages и live destructive Telegram calls.

## Stage 4L HelpDesk IMAP Inbox

- Stage 4L добавляет только один HelpDesk/GLPI IMAP mailbox, настроенный через Railway Variables или локальный `.env`.
- HelpDesk IMAP по умолчанию выключен: `HELPDESK_IMAP_ENABLED=false`.
- Обязательные runtime переменные при включении: `HELPDESK_IMAP_HOST`, `HELPDESK_IMAP_USERNAME`, `HELPDESK_IMAP_PASSWORD`, `HELPDESK_TELEGRAM_CHAT_ID`; порт/SSL/folder/filter/prefix/interval/mark-seen имеют defaults.
- IMAP password никогда не вводится через Telegram и не показывается в `/settings`, `/status`, docs, logs или PR.
- Worker job `check_helpdesk_imap_mailbox` делает polling, а не IMAP IDLE; если config disabled/incomplete, job no-op/sanitized warning и не падает.
- При первом успешном включении HelpDesk IMAP без mailbox state worker ставит baseline на текущий максимальный UID и не отправляет старые письма из INBOX.
- После baseline worker обрабатывает только новые письма с UID больше сохранённого `last_seen_uid`; новый комментарий к старой заявке должен отправляться, потому что это новое email message с новым UID.
- Если IMAP `UIDVALIDITY` изменился, worker безопасно ставит новый baseline на current max UID, логирует sanitized `helpdesk_imap_uidvalidity_changed` и не рассылает весь mailbox заново.
- Admin-only команда `/helpdesk_baseline_now` подключается к IMAP, сохраняет текущий max UID как baseline и не отправляет Telegram notifications за старые письма.
- `/status` показывает только stored diagnostics из Redis/PostgreSQL: enabled/configured, host configured/missing, port, ssl, masked username, folder, telegram chat id configured/missing, missing config keys, last check/success/error, baseline set/not set, last seen uid, mailbox last check/success/error, processed last 24h, pending notifications и failed notifications. Если failed notifications > 0, `/status` показывает короткое attention-предупреждение. `/status` не подключается к IMAP live.
- IMAP SSL client использует default TLS context; legacy fallback `SECLEVEL=1` разрешён только точечно после `DH_KEY_TOO_SMALL` от старого IMAP сервера.
- IMAP чтение использует `BODY.PEEK[]`; письма не помечаются прочитанными в MVP при `HELPDESK_MARK_SEEN=false`.
- Если `HELPDESK_MARK_SEEN=true`, `Seen` ставится только после успешной Telegram notification.
- GLPI parser deterministic и без LLM: поддерживает `Новая заявка`, `Новый комментарий`, `Заголовок`, `Описание`, `ФИО`, `Должность`, `Руководитель`, `Предварительная дата выхода`, `Настроить доступы`, URL и счётчики.
- Telegram карточка заявки использует safe HTML; весь текст из email проходит escaping; кнопка `Открыть заявку` не отправляется по умолчанию, потому что HelpDesk URL внутренний.
- Дедупликация хранится в PostgreSQL `helpdesk_email_events` по `Message-ID` и `(folder, imap_uid)`, чтобы повторный polling не создавал duplicate Telegram cards.
- В логах нельзя печатать тело письма целиком, raw email, полный sender email, IMAP password, Telegram token, API keys, Authorization headers или provider response body.
- Stage 4L не включает Telegram-ввод пароля, несколько mailbox-ов, email replies, удаление писем, mark-seen по умолчанию, RAG/OCR, Smart Watcher, multi-mailbox UI и live destructive Telegram calls.
- Railway Variables не меняются в PR; после merge пользователь добавляет их вручную в Railway UI.

## Stage 4L-2 HelpDesk Ticket Workflow

- Stage 4L-2 добавляет workflow заявок поверх уже принятого HelpDesk IMAP inbox: email reading остаётся read-only через `BODY.PEEK[]`, без email replies, удаления писем и mark-seen по умолчанию.
- Work items хранятся в PostgreSQL `helpdesk_ticket_work_items` по unique `(glpi_ticket_id, telegram_chat_id)`.
- Новая GLPI заявка создаёт/обновляет work item в статусе `waiting_ack`, добавляет в Telegram карточку кнопку `В работу`, ставит `reminder_interval_minutes=10` и `next_reminder_at=now+10m`.
- Повторное письмо с тем же `glpi_ticket_id` не создаёт дубль; status `done` не переоткрывается автоматически для того же ticket id.
- Callback `hd_ticket:take:<id>` доступен только admin/allowed user в текущем HelpDesk chat, переводит заявку в `in_work`, сохраняет `assigned_by_user_id`, `assigned_at`, `reminder_interval_minutes=30`, `next_reminder_at=now+30m`.
- Команда `/ticket` показывает заявки в работе; другие алиасы не добавляются.
- В карточке заявки в работе используются кнопки `Готово` и `Отложить 1ч`; callbacks `hd_ticket:done:<id>` и `hd_ticket:snooze:<id>:60` обязательно access-gated.
- Worker cron `remind_helpdesk_tickets` запускается раз в минуту, использует Redis claim `helpdesk_ticket:reminder:<id>` против duplicate reminders и отправляет reminders только для `waiting_ack`/`in_work`.
- Reminder `waiting_ack`: `Новая заявка GLPI #... ещё не взята в работу.` с кнопкой `В работу`; после успешной отправки следующий reminder через 10 минут.
- Reminder `in_work`: `Заявка GLPI #... всё ещё в работе.` с кнопками `Готово` и `Отложить 1ч`; после успешной отправки следующий reminder через 30 минут.
- Telegram send failure не продвигает `next_reminder_at`; retry остаётся возможен на следующем cron run.
- Все Telegram HTML тексты экранируют пользовательские/email-derived поля через `html.escape`; callback data не содержит email body, title, URL или secrets.
- Stage 4L-2 не добавляет внутреннюю ticket URL button, Railway Variables changes, destructive Telegram/IMAP calls, Smart Watcher, RAG/OCR, multi-mailbox UI и чтение/ответы на письма.

## Stage 4L-3 HelpDesk Vacation Mode

- Vacation Mode не отключает HelpDesk IMAP polling: worker продолжает читать новые письма через `BODY.PEEK[]`, сохранять events/work items, дедуплицировать и двигать `last_seen_uid`.
- Когда отпуск включён, автоматические Telegram карточки по новым HelpDesk событиям не отправляются; event фиксируется как `notify_status=suppressed_vacation`, `error_code=vacation`, и это не считается failed notification.
- Когда отпуск включён, `waiting_ack` reminders каждые 10 минут и `in_work` reminders каждые 30 минут не отправляются.
- Reminder suppression не должен создавать backlog flood: while vacation enabled active reminders переносятся на будущий normal interval, а при выключении отпуска active reminders ставятся на `now + reminder_interval_minutes`.
- При выключении отпуска старые накопленные vacation events остаются только для ручного просмотра; автоматическая отправка задним числом запрещена.
- Ручной review `Показать новые за отпуск` показывает первый раз всё с `enabled_at`, затем только events после `last_reviewed_at`; cursor обновляется только после успешной отправки review message.
- Если review send падает, `last_reviewed_at` не меняется, чтобы следующий review не потерял события.
- `/helpdesk_vacation`, `/helpdesk_vacation_on`, `/helpdesk_vacation_off` и `/settings -> HelpDesk` доступны только admin или тем же allowed users/groups, что HelpDesk ticket controls.
- Unknown group users не могут включать/выключать отпуск или запускать review.
- `/status` показывает только sanitized vacation diagnostics: mode, since, last reviewed, new since start и new since last review; Telegram IDs, email body, full addresses и secrets не выводятся.
- Stage 4L-3 не меняет Railway Variables, IMAP credentials, mailbox cleanup, mark-seen/delete поведение, email replies, Smart Watcher, RAG/OCR и multi-mailbox UI.

## Stage 1A/2A Structured Rich Cards And Event Inbox

- Event Center foundation хранит события в PostgreSQL `event_items`.
- Поддерживаемые scope: `personal`, `household`, `work`, `system`.
- Поддерживаемые statuses: `new`, `seen`, `done`, `snoozed`, `archived`, `failed`.
- Поддерживаемые priorities: `low`, `normal`, `high`, `critical`.
- Поддерживаемые event types: `reminder`, `note`, `shopping`, `helpdesk_ticket`, `whoop_sleep`, `system_alert`, `digest_item`.
- `card_json` хранит Structured Rich Card с полями `type`, `title`, `severity`, `facts[]`, `summary`, `actions[]`.
- Telegram renderer карточек обязан экранировать HTML и никогда не показывать пользователю raw JSON.
- `/inbox` показывает только active события scope `personal` и `household`; `work` и `system` туда не попадают.
- `/work` показывает только active события scope `work`; `personal`, `household` и `system` туда не попадают.
- HelpDesk/tickets относятся к `work` events и не должны попадать в `/inbox`.
- Сортировка выдачи: priority desc, `due_at` asc с nulls last, затем `created_at` desc; лимит MVP — 10 событий.
- Callback data для карточек остаётся коротким и стабильным: `event:<action>:<event_id>`, без пользовательского текста, JSON, prompt, токенов или secrets.
- Callback actions `done`, `snooze`, `details` должны быть отдельно access-gated, потому что message middleware не защищает callback queries.
- Default digest timezone зафиксирован как `Europe/Moscow`.
- Stage 1A/2A не реализует WHOOP OAuth/sync, AI-анализ сна, digest scheduling, production deploy, Railway config changes и HelpDesk migration в `event_items`.

## Stage 3 Event Inbox Digests

- Scheduled digests строятся только из `event_items`.
- Default policies хранятся в PostgreSQL таблице `digest_policies`.
- `personal_morning`: `06:50 Europe/Moscow`, scopes `personal`, `household`.
- `work_start`: `09:00 Europe/Moscow`, scope `work`.
- Личный дайджест не должен включать `work`, HelpDesk/tickets и `system`.
- Рабочий дайджест не должен включать `personal`, `household` и `system`.
- `system` events не включаются по умолчанию.
- `target_chat_id` не угадывается и не берётся из env secrets; если chat не настроен, policy считается chat missing и worker её не отправляет.
- Chat для policy задаётся вручную через `/settings -> Дайджесты -> Использовать этот чат` только из личного чата администратора.
- `/digest` показывает admin-only status policies и кнопки show-now/settings.
- `/settings -> Дайджесты` доступен только env admin из `ADMIN_TELEGRAM_IDS`.
- Edit time принимает только `HH:MM`, edit timezone валидируется как IANA timezone через `zoneinfo.ZoneInfo`; `/cancel` очищает FSM input.
- Worker job `send_due_digests` запускается cron раз в минуту.
- Worker должен поставить Redis claim `digest:send:{policy_key}:{local_date}` до Telegram send; duplicate claim не отправляет digest.
- При успешной Telegram отправке worker обновляет `last_sent_date` и `last_sent_at`; при Telegram send failure не mark-ит sent и удаляет claim, чтобы retry был возможен.
- Grace window расписания — 30 минут: `06:50` можно отправить до `07:20`, `09:00` до `09:30`; после окна MVP пропускает digest до следующего дня и не создаёт backlog flood.
- Digest renderer использует Telegram HTML, экранирует пользовательский текст через `html.escape`, не показывает raw JSON/payload/secrets и держится в лимите Telegram.
- WHOOP/OAuth в Stage 3 не включается.
- HelpDesk migration в `event_items` в Stage 3 не выполняется, если это расширяет scope.

## Logging Hygiene

- Normal operational app logs уровня `DEBUG`/`INFO` должны писаться в stdout; реальные warning/error/exception остаются на stderr.
- Central logging config находится в `app/core/logging.py`; API startup и arq worker должны использовать один и тот же redaction filter.
- Redaction обязана маскировать Telegram Bot API URLs вида `https://api.telegram.org/bot<TOKEN>/...`, Telegram token, Authorization/Bearer headers, API keys, passwords, webhook secrets и nested `extra` values.
- Redaction применяется не только к `record.msg`, `record.args` и structured `extra`, но и к финальной formatted log string и `formatException`; `logger.exception(...)` и `logger.error(..., exc_info=True)` должны сохранять stack trace, но без token/header/secret-bearing traceback text.
- `httpx`, `httpcore` и `aiohttp` request info logs не должны печатать полный Telegram Bot API URL; по умолчанию они понижены до `WARNING`.
- Webhook self-healing logs остаются только sanitized событиями `telegram_webhook_setup_started`, `telegram_webhook_setup_completed`, `telegram_webhook_setup_failed`, `webhook_host`, `webhook_path` и sanitized error fields.
- Если arq или Railway помечают сторонний runtime stderr как `[err]`, это не считается ошибкой без traceback, failed exit code или failed job marker; app-controlled logs должны быть stdout/stderr-clean.

## Проверки

Перед финальным отчётом выполнять:

```bash
uv run --python 3.12 --extra dev ruff check .
uv run --python 3.12 --extra dev mypy app
uv run --python 3.12 --extra dev pytest -q
docker compose build
docker compose up -d
docker compose ps
docker compose logs --tail=100 api
docker compose logs --tail=100 worker
docker compose exec api alembic upgrade head
docker compose exec api pytest -q
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8000/ready
uv run --python 3.12 --extra dev python scripts/smoke_llm.py
uv run --python 3.12 --extra dev python scripts/smoke_polling_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_regular_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_group_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_streaming_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_mira_private_streaming_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_thinking_text_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_lists_reminders_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_lists_reminders_ux_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_daily_brief_shopping_v2_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_provider_settings_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_access_settings_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_private_ingress_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_telegram_update_idempotency_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_prompt_profiles_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_status_household_context_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_helpdesk_imap_readiness.py
git status --short
```

## Remote AGENTS sync

Серверные/live project paths в этом репозитории не заведены.

`remote AGENTS sync = N/A until server/live paths exist`
