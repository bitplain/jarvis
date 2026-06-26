# Jarvis Telegram AI Bot

Jarvis — production-ready каркас Telegram AI bot для Ubuntu Server с Docker Compose.

## Матрица режимов

| Режим | Для обычного Telegram-аккаунта | Что умеет | Ограничения |
| --- | --- | --- | --- |
| Regular Assistant Mode | Да | Личка с ботом, подготовка ответов, работа с пересланным текстом | Бот видит только то, что пользователь отправил боту |
| Group Assistant Mode | Да, если бот добавлен в группу | Ответ на mention или reply на сообщение бота | Не читает всю историю группы; privacy mode Telegram может ограничивать updates |
| Guest Mode | Да | Вызов через `@bot_username` в чатах, куда бот не добавлен | Работает только через Telegram `guest_message` |
| Business / Secretary Mode | Нет, только Telegram Business / Secretary | Ответ через `business_connection_id` при `can_reply` | Нужны Business connection и права Telegram Business |
| Чтение личных входящих обычного пользователя | Нет | Невозможно через Bot API | Для этого Bot API не подходит; userbot/MTProto в проекте не используется |

Главный путь Jarvis для обычного аккаунта — Regular Assistant Mode.
Business / Secretary Mode не нужен для обычного использования и оставлен optional-модулем.

## Быстрый запуск

```bash
cp .env.example .env
docker compose build
docker compose up -d
docker compose exec api alembic upgrade head
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8000/ready
```

Логи:

```bash
docker compose logs -f api
docker compose logs -f worker
```

Тесты в контейнере:

```bash
docker compose exec api pytest -q
```

## Deployment

Локальный Docker Compose flow остаётся основным режимом разработки и smoke на Mac.
Production deploy на Railway описан в `docs/RAILWAY_DEPLOY.md`.

Railway production запускается в webhook mode: отдельный service для API/webhook, отдельный service для arq worker, отдельные Railway PostgreSQL и Railway Redis. Polling используется только для local/Mac smoke и не должен работать параллельно с production webhook runtime.

При `APP_ENV=production` `jarvis-api` выполняет Telegram webhook self-healing setup на startup после миграций: использует `PUBLIC_BASE_URL`, `TELEGRAM_BOT_TOKEN` и `TELEGRAM_WEBHOOK_SECRET`, логирует только sanitized `webhook_host`/`webhook_path` и не валит startup при отсутствующем env или временной ошибке Telegram API. Worker webhook setup не выполняет.

## Куда вставлять секреты

Секреты вставляются только в локальный `.env`, который не попадает в git:

- `TELEGRAM_BOT_TOKEN` — token из BotFather.
- `TELEGRAM_WEBHOOK_SECRET` — секрет для Telegram webhook header.
- `ADMIN_API_TOKEN` — Bearer token для `GET /admin/models`.
- `YANDEX_AI_API_KEY` — ключ Yandex AI Studio.
- `OPENROUTER_API_KEY` — ключ OpenRouter.

Не вставляйте секреты в код, README, AGENTS, workflow-файлы или отчёты.

Для безопасной подготовки реального `.env` можно использовать Stage 1R bootstrap:

```bash
uv run --python 3.12 --extra dev python scripts/bootstrap_real_env.py --dry-run
uv run --python 3.12 --extra dev python scripts/bootstrap_real_env.py --apply
```

Если нужно временно перейти с webhook на polling для получения `ADMIN_TELEGRAM_IDS`, используйте явный флаг. Pending updates по умолчанию сохраняются:

```bash
uv run --python 3.12 --extra dev python scripts/bootstrap_real_env.py --apply --delete-webhook-for-getupdates
```

Подробности: `docs/STAGE_1R_ENV_BOOTSTRAP.md`.

Для локального Telegram webhook без сервера нужен публичный HTTPS tunnel до `http://localhost:8000`.
Инструкция: `docs/STAGE_1R_TUNNEL_SETUP.md`.
Финальный user-originated smoke отчёт: `docs/STAGE_1R_FINAL_LIVE_TELEGRAM_REPORT.md`.

Webhook и LLM smoke:

```bash
uv run --python 3.12 --extra dev python scripts/set_telegram_webhook.py
uv run --python 3.12 --extra dev python scripts/set_telegram_webhook.py --info
uv run --python 3.12 --extra dev python scripts/smoke_llm.py
```

## Обязательные переменные

Для локального каркаса без реальных Telegram/LLM вызовов достаточно значений из `.env.example`.

Для работы бота нужны:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_BOT_USERNAME`
- `TELEGRAM_WEBHOOK_SECRET`
- `ADMIN_TELEGRAM_IDS`
- `ADMIN_API_TOKEN`
- `REGULAR_ASSISTANT_ENABLED`
- `FORWARDED_MESSAGE_ASSISTANT_ENABLED`
- `DRAFT_REPLY_ENABLED`
- `GROUP_ASSISTANT_ENABLED`
- `GUEST_MODE_ENABLED`
- `GUEST_MODE_ADMIN_ONLY`
- `GUEST_MODE_MAX_TOKENS`
- `STREAMING_ENABLED`
- `STREAMING_PRIVATE_DRAFT_ENABLED`
- `STREAMING_GROUP_FALLBACK_ENABLED`
- `TELEGRAM_PRIVATE_DRAFT_STREAMING_ENABLED`
- `STREAMING_DRAFT_UPDATE_INTERVAL_MS`
- `STREAMING_GROUP_EDIT_INTERVAL_MS`
- `STREAMING_MIN_CHARS_DELTA`
- `STREAMING_MAX_DRAFT_SECONDS`
- `STREAMING_SEND_CHAT_ACTION_INTERVAL_SECONDS`
- `STREAMING_DRAFT_RAW_API_FALLBACK`
- `YANDEX_AI_BASE_URL`
- `YANDEX_AI_API_KEY`
- `YANDEX_AI_MODEL`
- `OPENROUTER_API_KEY`
- `OPENROUTER_MODEL`

Yandex OpenAI-compatible base URL обычно указывается как:

```env
YANDEX_AI_BASE_URL=https://ai.api.cloud.yandex.net/v1
```

Model IDs не заданы в коде намеренно. Их нужно задавать только через `.env`.

Business-переменные optional и нужны только для Telegram Business / Secretary Mode:

- `BUSINESS_MODE_ENABLED`
- `BUSINESS_ADMIN_ONLY`
- `BUSINESS_REPLY_ENABLED`
- `BUSINESS_REPLY_TRIGGER`
- `BUSINESS_MEMORY_MAX_MESSAGES`
- `BUSINESS_ALLOWED_CONNECTION_IDS`
- `BUSINESS_ALLOWED_CHAT_IDS`

## Endpoints

- `GET /health` — процесс жив.
- `GET /ready` — PostgreSQL и Redis доступны.
- `POST /telegram/webhook` — вход Telegram updates.
- `GET /admin/models` — диагностика моделей Yandex/OpenRouter, требует Bearer token из `ADMIN_API_TOKEN`.

## `/status` и ручная память

Stage 4I заменяет старый `/status` на admin-only диагностику Telegram-бота.

Команда `/status` доступна только env admin из `ADMIN_TELEGRAM_IDS`. В private chat non-admin получает `Доступ запрещён.`, в group/supergroup системный статус не раскрывается обычным пользователям.

Поля `/status`:

- API process;
- PostgreSQL connectivity и latency;
- Redis connectivity и latency;
- worker heartbeat `jarvis:worker:heartbeat`;
- webhook configured/unknown без live destructive calls;
- due reminders count без текста напоминаний;
- active LLM provider (`Auto`, `Yandex`, `OpenRouter`);
- draft streaming enabled/disabled;
- prompt profiles DB status;
- access DB status.

Stage 4I также добавляет household context foundation: ручную память только по явным командам.

Примеры private chat:

- `запомни: у нас семейный чат Фемилис`
- `запомни что молоко обычно добавлять в список покупок`
- `что ты помнишь?`
- `забудь: у нас семейный чат Фемилис`

В group/supergroup память работает только через mention/reply, например:

- `@bot_username запомни: это семейный чат Фемилис`
- `@bot_username что ты помнишь?`

Данные хранятся в PostgreSQL таблице `household_memory_entries`, отдельно по scope `private` или `group`. Active entries текущего scope добавляются в LLM system prompt коротким блоком `Память о текущем чате`, максимум 20 записей / 2000 символов. Память из других чатов не подмешивается и не используется для access decisions.

Безопасность Stage 4I:

- watcher не включается;
- авто-запоминания из обычных сообщений нет;
- group messages без mention/reply не читаются ради памяти;
- voice/media/transcription не добавляются;
- secret-looking текст (`token`, `password`, `api key`, `Authorization`) не сохраняется.

Readiness без live Telegram calls:

```bash
uv run --python 3.12 --extra dev python scripts/smoke_status_household_context_readiness.py
```

Ожидаемый verdict: `PASS_STATUS_HOUSEHOLD_CONTEXT_READINESS`.

## Настройки LLM-провайдера

Stage 4D добавляет admin-only Telegram UI для выбора активного LLM-агента без изменения `.env` и без ручного изменения Railway Variables.

Открыть настройки можно командой `/settings` или кнопкой `Настройки` после `/start`.

Варианты:

- `Auto` — использует текущую env-логику `LLM_PRIMARY_PROVIDER` и `LLM_FALLBACK_PROVIDER`.
- `Yandex` — принудительно выбирает Yandex provider для следующих worker jobs.
- `OpenRouter` — принудительно выбирает OpenRouter provider для следующих worker jobs.

Выбор хранится в PostgreSQL runtime setting `active_llm_provider` в таблице `runtime_settings`. Если записи нет, Jarvis ведёт себя как `auto`.

Production API автоматически выполняет `alembic upgrade head` перед стартом `uvicorn`, поэтому таблица `runtime_settings` должна создаваться без ручного шага. Stage 4E добавляет code-level startup migration guard: даже если Railway UI Start Command переопределит `railway.api.toml`, API в production сначала применит миграции.

Webhook state хранится на стороне Telegram, поэтому production API дополнительно self-heal-ит webhook на startup: после успешных миграций пробует установить `<PUBLIC_BASE_URL>/telegram/webhook`. Ошибки setup логируются sanitized событиями `telegram_webhook_setup_failed` и не останавливают API.

Railway Variables всё равно нужны: ключи и model ids `YANDEX_*` и `OPENROUTER_*` остаются только в `jarvis-worker` variables и не отображаются в Telegram UI, логах или документации.

Readiness без секретов:

```bash
uv run --python 3.12 --extra dev python scripts/smoke_provider_settings_readiness.py
```

Ожидаемый verdict: `PASS_PROVIDER_SETTINGS_READINESS`.

Stage 4E также делает callback-кнопки идемпотентными: повторный `Refresh`, повторный выбор текущего provider и Telegram `message is not modified` не должны превращаться в HTTP 500 webhook.

## Промты и стиль ответа

Stage 4F-2 hotfix добавляет admin-only раздел `/settings -> Промты`.

Raw prompt editor показывает текущий system prompt, позволяет переписать его вручную, сохранить custom prompt и сбросить к default:

- `prompt.private` — prompt для обычных private chat сообщений;
- `prompt.group` — prompt для group/supergroup mention/reply;
- `prompt.watch` — заготовка для будущего watcher, ничего автоматически не запускает.

Значения хранятся в существующей PostgreSQL таблице `runtime_settings`. Если custom prompt отсутствует, UI показывает default prompt и источник `default`; если custom prompt сохранён, UI показывает источник `custom`. Максимальная длина custom prompt: 4000 символов. Длинный prompt показывается preview в экране настроек, а кнопка `Показать полностью` отправляет полный текст отдельным plain-text сообщением без `parse_mode`.

Старые пресеты `balanced`, `short`, `deep`, `draft`, `watcher` остаются отдельным разделом `/settings -> Стиль ответа` и не считаются заменой raw prompt editor.

Stage 4F-2 не включает Smart Watcher, чтение всех сообщений, изменение streaming или эффект Mira.

Private ingress остаётся release gate для Stage 4F-2: `/start` должен отвечать через webhook, обычный private text от admin/allowed user должен создавать `process_llm_message`, unknown private user должен получать `Доступ запрещён.`, а prompt edit FSM должен перехватывать следующий private text и не отправлять его в LLM. Временная недоступность Redis не должна валить `/start` до command handler.

Readiness без секретов и без `getUpdates`:

```bash
uv run --python 3.12 --extra dev python scripts/smoke_private_ingress_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_prompt_profiles_readiness.py
```

Ожидаемые verdict: `PASS_PRIVATE_INGRESS_READINESS` и `PASS_PROMPT_PROFILES_RAW_EDITOR_READINESS`.

## Списки покупок и напоминания

Stage 4G добавляет собственные PostgreSQL-backed списки покупок и напоминания через явные Telegram-команды. Telegram Business checklists, native Telegram reminders, watcher и LLM parsing не используются.

Примеры private chat:

- `добавь хлеб в список покупок`
- `добавь молоко, яйца и сыр в список`
- `покажи список покупок`
- `что купить?`
- `удали молоко из списка`
- `очисти купленное`
- `напомни завтра в 10 купить молоко`
- `напомни через 30 минут проверить духовку`
- `напомни 28.06 в 14:00 оплатить счёт`
- `покажи напоминания`

В group/supergroup эти же команды работают только через mention/reply, например `@bot_username добавь хлеб в список покупок`. Обычные group messages без mention/reply остаются silent.

Shopping parser deterministic: несколько позиций можно передать через запятую, точку с запятой, новую строку или простой connector `и`, например `мазик и молоко` -> `мазик`, `молоко`. Текущий bot mention внутри shopping item payload вырезается перед сохранением, поэтому `@Home_ai_my_bot творожок` сохраняется как `творожок`.

Данные хранятся в таблицах `shopping_lists`, `shopping_list_items` и `reminders`. Private список scoped по user id, group список scoped по chat id. Напоминания доставляет arq worker job `deliver_due_reminders`; overdue reminders после рестарта остаются scheduled и будут доставлены следующим worker tick.

Ответы форматируются Telegram HTML (`parse_mode="HTML"`), пользовательский текст экранируется через `html.escape`. Inline-кнопки позволяют отметить покупку, вернуть её, удалить item, очистить купленное, выполнить/удалить/snooze напоминание на 10 минут или 1 час.

Stage 4G-1 улучшает UX без watcher и без Telegram Business:

- `/settings -> Списки и напоминания` показывает текущий timezone, help, личные active reminders и личный список покупок.
- Timezone хранится в `runtime_settings` ключом `lists.timezone`; default `Europe/Moscow`. Ввод валидируется как IANA timezone через `zoneinfo.ZoneInfo`, например `Europe/Moscow`, `Europe/Amsterdam`, `Asia/Dubai`.
- Timezone влияет на parsing `напомни завтра в 10 ...`, отображение reminder create/list и due reminder delivery. В БД reminder time остаётся UTC.
- Help-фразы `помощь список`, `помощь напоминания`, `как пользоваться списком`, `как пользоваться напоминаниями` показывают HTML help и не отправляют текст в LLM.
- Список покупок показывает `➕ Добавить`, `✅ Очистить купленное` и `🧹 Очистить всё`. Полная очистка требует confirmation.
- Список напоминаний показывает кнопки `✅ Выполнено`, `⏰ +10 мин`, `⏰ +1 час`, `🗑 Удалить` и `➕ Добавить напоминание`.
- Add-flow для покупок и напоминаний работает через FSM и перехватывает следующий text до generic LLM handler.

Stage 4G-1 не включает watcher, voice/transcription, Telegram Business integration, изменение Railway Variables и PR #5.

Readiness без live Telegram/LLM calls:

```bash
uv run --python 3.12 --extra dev python scripts/smoke_lists_reminders_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_lists_reminders_ux_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_shopping_parser_sanitize_readiness.py
```

Ожидаемые verdict: `PASS_LISTS_REMINDERS_READINESS`, `PASS_LISTS_REMINDERS_UX_READINESS` и `PASS_SHOPPING_PARSER_SANITIZE_READINESS`.

## Настройки доступа

Stage 4F-1 добавляет admin-only раздел `/settings -> Доступ`.

Команда `/whoami` показывает текущие Telegram user ID, тип чата и chat ID. В group/supergroup она дополнительно показывает, разрешены ли именно текущий user и текущая group. Она доступна всем и нужна, чтобы безопасно узнать ID без просмотра `.env` или логов.

В `/settings -> Доступ` env admin может:

- посмотреть разрешённых пользователей;
- добавить пользователя по Telegram user ID;
- удалить пользователя;
- посмотреть разрешённые группы;
- добавить группу по Telegram chat ID;
- удалить группу.

Записи хранятся в PostgreSQL таблице `telegram_access_entries`. `ADMIN_TELEGRAM_IDS` остаются главными админами из env, всегда имеют доступ и не переносятся в таблицу автоматически. DB allowed user получает доступ к Jarvis, но не становится admin и не может управлять `/settings`.

Если разрешённых групп нет, сохраняется старая совместимость: authorized user может вызвать Jarvis в любой группе через mention/reply. После добавления хотя бы одной группы включается group allowlist mode: нужны и разрешённый user, и разрешённая group.

Access input поддерживает:

- один ID с подписью: `5117224471 Александр`;
- несколько IDs через пробел: `5117224471 291844566`;
- несколько IDs по строкам.

Webhook runtime должен использовать один persistent aiogram Dispatcher на app instance: access FSM state хранится в Dispatcher storage между callback update и следующим message update.

Readiness без секретов:

```bash
uv run --python 3.12 --extra dev python scripts/smoke_access_settings_readiness.py
```

Ожидаемый verdict: `PASS_ACCESS_SETTINGS_READINESS`.

## Guest Mode

Stage 2 реализует Telegram Guest Mode через update type `guest_message`.

- Включается только через `GUEST_MODE_ENABLED=true`.
- По умолчанию доступен только владельцу из `ADMIN_TELEGRAM_IDS`: `GUEST_MODE_ADMIN_ONLY=true`.
- Отвечает одним финальным `answerGuestQuery`, без streaming и без `sendMessageDraft`.
- Не использует обычную память личного/группового чата и не сохраняет постоянную память чужого guest-чата.
- Учитывает только текст вызова и replied message, если Telegram его передал.

Ручной smoke: `docs/STAGE_2_GUEST_MODE_REAL_SMOKE.md`.
Итоговый отчёт: `docs/STAGE_2_GUEST_MODE_REPORT.md`.

### Локальный polling smoke на Mac

Если публичный HTTPS tunnel недоступен, Guest Mode можно проверять через Telegram polling.
Polling удаляет webhook и получает updates через `getUpdates`, поэтому tunnel не нужен.
При `APP_ENV=production` polling readiness и polling runner не выполняют `deleteWebhook`: production webhook runtime нельзя отключать диагностическим smoke.

Host-side overrides без секретов:

```bash
cp .env.polling.example /tmp/jarvis-polling-env-example
```

В локальном `.env` для Mac обычно нужны:

```env
POSTGRES_HOST=localhost
REDIS_URL=redis://localhost:6379/0
GUEST_MODE_ENABLED=true
GUEST_MODE_ADMIN_ONLY=true
```

Локальный `docker-compose.override.yml` публикует Postgres `5432` и Redis `6379` для host-side polling runner.

Readiness без получения updates:

```bash
uv run --python 3.12 --extra dev python scripts/smoke_polling_readiness.py
```

Запуск polling:

```bash
uv run --python 3.12 --extra dev python scripts/run_polling.py
```

Подробности: `docs/STAGE_2R_GUEST_MODE_POLLING_SMOKE.md`.

## Как пользоваться без Telegram Business

### Личка с ботом

Напишите боту обычный запрос в private chat. Jarvis сохранит сообщение в обычную chat memory и подготовит ответ через worker.

Пример:

```text
Составь список вопросов для созвона с подрядчиком
```

### Пересылка сообщения боту

Перешлите сообщение в личку Jarvis. Бот сохранит пересланный текст как отдельный context item и предложит команды:

```text
/summary
/draft_reply
/translate
/factcheck
```

### Черновик ответа

Чтобы подготовить ответ клиенту без отправки от имени пользователя:

```text
Ответь на это:
Клиент спрашивает, когда будет готов макет
```

Jarvis вернёт черновик. Пользователь сам копирует и отправляет его в нужный чат.

### Группы

Если бот добавлен в группу, он отвечает только на mention `@bot_username` или reply на сообщение бота.
Если privacy mode Telegram ограничивает updates, Jarvis честно работает только с теми сообщениями, которые Telegram передал боту.
Вызов `@bot_username`, который Telegram доставляет как `guest_message`, относится к Guest Mode и не доказывает работу Group Assistant.
Для live smoke group mention/reply должны появиться как обычные group/supergroup `message` updates, создать regular memory запись и worker job.

### Streaming UX

Stage 3A-S добавляет streaming UX для обычного assistant path.

- Private chat: worker пробует Telegram `sendMessageDraft` с non-zero `draft_id`, обновляет draft через `StreamBuffer` с throttling, а после завершения отправляет финальный `sendMessage`. В БД сохраняется только финальный assistant response.
- Mira-style private streaming: при `TELEGRAM_PRIVATE_DRAFT_STREAMING_ENABLED=true` private chat сначала пробует `sendRichMessageDraft` с rich thinking block `Думаю`, затем обновляет тот же `draft_id` через text draft updates. Webhook не отправляет отдельное обычное thinking-сообщение для этого режима; финальный ответ всё равно отправляется обычным `sendMessage`.
- Private fallback: если draft API недоступен или вернул ошибку, текущий LLM job переключается на provisional/edit path с коротким `Думаю` без вывода token/key/header в logs.
- Group chat: `sendMessageDraft` не используется. Worker отправляет `sendChatAction typing`, один provisional `Думаю`, затем throttled `editMessageText` и финальный edit. Если финальный edit не прошёл, отправляется fallback final `sendMessage` ровно один раз; повторная finalization ничего не отправляет.
- Unauthorized group/supergroup сообщения молча игнорируются, чтобы бот не спамил `Доступ запрещён`; в private chat явный отказ остаётся.
- Guest Mode: остаётся final-only через `answerGuestQuery`, без streaming, draft и group edit sink.
- Business / Secretary: auto-reply не включается; streaming слой только подготовлен к fallback path с `business_connection_id` для `sendChatAction`.
- Длинные финальные ответы делятся на Telegram-safe chunks при отправке, но в БД сохраняется один полный assistant response.

Readiness без получения Telegram updates:

```bash
uv run --python 3.12 --extra dev python scripts/smoke_streaming_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_mira_private_streaming_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_group_stability_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_telegram_webhook_ingress_readiness.py
```

Отчёт Stage 3A-S: `docs/STAGE_3A_S_STREAMING_UX_REPORT.md`.
Отчёт Stage 4F-3: `docs/STAGE_4F3_MIRA_PRIVATE_STREAMING_REPORT.md`.
Live smoke отчёт: `docs/STAGE_3A_S_STREAMING_LIVE_REPORT.md`.

### Guest Mode

В чатах, куда бот не добавлен, используйте Guest Mode через `@bot_username`, если Telegram присылает update type `guest_message`.

Regular readiness без Business account:

```bash
uv run --python 3.12 --extra dev python scripts/smoke_regular_readiness.py
```

## Business Mode / Secretary Foundation

Stage 3A оставляет безопасный optional foundation для Telegram Business Mode.
Этот режим не работает для обычного аккаунта без Telegram Business / Secretary connection.

- сохраняет `business_connection`, `business_message`, `edited_business_message` и `deleted_business_messages` в PostgreSQL;
- проверяет owner через `ADMIN_TELEGRAM_IDS`, `is_enabled`, `can_reply`, allowlist connection/chat при наличии;
- не включает автоответчик по умолчанию;
- отвечает только при явных `BUSINESS_MODE_ENABLED=true`, `BUSINESS_REPLY_ENABLED=true` и trigger `BUSINESS_REPLY_TRIGGER`;
- отправляет ответ typed aiogram `sendMessage` с `business_connection_id`;
- использует отдельную business-memory по `business_connection_id + chat_id`.

Readiness без получения updates:

```bash
uv run --python 3.12 --extra dev python scripts/smoke_business_readiness.py
```

Ручной real smoke: `docs/STAGE_3A_BUSINESS_MODE_REAL_SMOKE.md`.
Итоговый отчёт: `docs/STAGE_3A_BUSINESS_MODE_FOUNDATION_REPORT.md`.

## Отложенные части

- Autonomous Secretary auto-reply — будущий этап после ручного Stage 3A smoke.
- Mini App — отдельный будущий этап.
