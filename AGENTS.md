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
- Stage 4C автоматизирует миграции через `preDeployCommand = "alembic upgrade head"` в `railway.api.toml`; Stage 4D дополнительно запускает `alembic upgrade head` в API start command перед `uvicorn`, чтобы webhook runtime не стартовал со старой схемой.
- Webhook на Railway устанавливается через sanitized script `scripts/setup_telegram_webhook.py` или совместимый `scripts/set_telegram_webhook.py`; scripts должны читать Railway process env и не печатать token/secret.
- API startup при `APP_ENV=production` выполняет Telegram webhook self-healing setup после startup migrations, использует тот же sanitized setup logic и логирует только `telegram_webhook_setup_started`, `telegram_webhook_setup_completed`, `telegram_webhook_setup_failed`, `webhook_host`, `webhook_path`.
- Webhook self-healing не запускается в worker, dev и test. Отсутствующий token/public URL/secret или временная ошибка Telegram API не должны валить API startup; нужно логировать sanitized failure без token/secret/header.
- Railway project/deploy/push/tag/release не создаются без отдельной команды.

## Stage 4D Provider Settings

- Активный LLM-агент переключается только через PostgreSQL runtime setting `active_llm_provider`, а не через изменение `.env` или Railway Variables.
- Допустимые значения: `auto`, `yandex`, `openrouter`; отсутствие записи означает `auto`.
- `auto` сохраняет env-based primary/fallback логику `LLM_PRIMARY_PROVIDER` и `LLM_FALLBACK_PROVIDER`.
- `yandex` и `openrouter` принудительно выбирают соответствующий provider для следующих worker jobs; worker должен читать setting перед обработкой job и не кэшировать выбор навечно.
- Telegram UI `/settings` и callback `settings:*` доступны только admin user из `ADMIN_TELEGRAM_IDS`; non-admin получает `Доступ запрещён.`
- Кнопка `Настройки` может показываться в `/start`, но обработчик всё равно обязан проверять admin access.
- Если выбранный provider не настроен или падает, пользователю показывается безопасная русская ошибка, а logs остаются sanitized без token/key/header/provider response body.
- Railway Variables `YANDEX_*` и `OPENROUTER_*` остаются обязательными для worker, но реальные значения нельзя выводить в Telegram UI, docs, logs или PR.
- API production start command должен автоматически выполнять `alembic upgrade head` перед стартом `uvicorn`; ручная миграция не должна быть обязательной для кнопки `Настройки`.
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
uv run --python 3.12 --extra dev python scripts/smoke_provider_settings_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_access_settings_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_private_ingress_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_prompt_profiles_readiness.py
git status --short
```

## Remote AGENTS sync

Серверные/live project paths в этом репозитории не заведены.

`remote AGENTS sync = N/A until server/live paths exist`
