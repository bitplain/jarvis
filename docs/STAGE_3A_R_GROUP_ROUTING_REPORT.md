# Stage 3A-R Group Routing Report

Дата: 2026-06-14

Стартовый commit: `79c7460 Stage 3A-R: validate regular assistant live smoke`

## Итог

Verdict: `PASS_STAGE_3A_R_GROUP_ROUTING_READY`

Group routing проверен через настоящий Telegram polling smoke без webhook/tunnel и без synthetic updates.

## BotFather / Telegram prerequisites

Пользователь подтвердил, что бот добавлен в настоящую тестовую группу. После настройки BotFather/privacy delivery polling runner начал получать обычные group/supergroup `message` updates.

Документ с ручными prerequisites добавлен:

- `docs/STAGE_3A_R_GROUP_ROUTING_CHECKLIST.md`

## Readiness

Выполнено до live smoke:

- `scripts/smoke_group_readiness.py`: `PASS_GROUP_READINESS`
- `scripts/smoke_polling_readiness.py`: `PASS_POLLING_READINESS`
- `scripts/smoke_regular_readiness.py`: `PASS_REGULAR_READINESS`
- `scripts/smoke_llm.py`: `PASS_LLM_SMOKE`

Sanitized group readiness подтвердил:

- `allowed_updates_message: OK`
- `group_router_registered: OK`
- `private_router_filter: OK`
- `group_router_filter: OK`
- `group_plain_ignore_test: OK`
- `group_mention_reply_test: OK`

## Polling runner

`scripts/run_polling.py` запускался локально через polling.

Startup evidence:

- `polling started`
- allowed updates содержали `message`
- webhook был удалён через readiness с `drop_pending_updates=false`
- business mode disabled
- business reply disabled
- admin ids выводились только как `SET count=1`

## Live group update evidence

Polling stdout показал настоящие group diagnostics:

- `INFO:app.bot.middlewares.group_diagnostics:group_message_update`
- `INFO:app.bot.routers.groups:group_message_routing`
- `INFO:aiogram.event:Update id=... is handled`

Для command mention path был виден прямой LLM provider HTTP 200 в polling runner, без вывода ключей.

## Manual scenarios

| Сценарий | Результат | Evidence |
| --- | --- | --- |
| Plain group message без mention/reply | PASS | group update пришёл; group routing diagnostics зафиксировал ignored path; DB/worker не получили лишний group row/job для plain ignore |
| `/status@bot_username` | PASS | command mention обработан как group message update; пользователь получил ответ в группе |
| `@bot_username текст` | PASS | group routing path дошёл до worker; пользователь подтвердил выполнение smoke |
| `/summary@bot_username аргумент` | PASS | command mention с inline argument обработан direct command path; provider HTTP 200 |
| reply на сообщение бота | PASS | group routing path обработан как reply-to-bot/manual group smoke; пользователь подтвердил выполнение |

Ограничение: stdout aiogram не печатает payload update, поэтому классификация сценариев фиксируется sanitized diagnostics + worker/DB evidence + ручное подтверждение пользователя, без вывода текста сообщений.

## Worker evidence

`docker compose logs --tail=500 worker` подтвердил group job:

- `process_llm_message({'chat_id': <group>, 'user_id': <masked>, 'private': False})`
- job завершился успешно

Это подтверждает, что group path не использовал private draft/streaming path.

## DB evidence

PostgreSQL sanitized checks:

- `messages`: появились group rows:
  - `group USER`: `1`
  - `group ASSISTANT`: `1`
- group USER row имел Telegram message id;
- group ASSISTANT row был сохранён как финальный ответ worker;
- existing private rows остались отдельными;
- `guest_messages_stub`: recent rows за smoke = `0`;
- `business_messages`: rows = `0`.

Полные Telegram IDs и тексты сообщений в отчёт не выводились.

## Исправления

- Добавлен sanitized group diagnostics middleware для обычных group/supergroup `message` updates до выбора router.
- Group handler логирует sanitized routing decision и enqueue status.
- Text mention / command mention / reply-to-bot классифицируются явно.
- Runtime bot username берётся из Telegram `get_me()` и имеет приоритет над потенциально stale `TELEGRAM_BOT_USERNAME`.
- `/command@other_bot` игнорируется.
- Пустой `@bot_username` отвечает: `Напиши запрос после упоминания бота.`
- `scripts/smoke_group_readiness.py` проверяет routing readiness без `getUpdates`.

## Regression tests

Добавлены/расширены:

- `tests/test_group_handler.py`
- `tests/test_group_diagnostics_middleware.py`
- `tests/test_context_commands.py`
- `tests/test_status_command.py`
- `tests/test_worker_jobs.py`
- `tests/test_smoke_group_readiness.py`

Покрыты:

- private router не является group handler;
- group router не обрабатывает private message;
- plain group message ignored;
- text mention processed;
- command mention current bot processed;
- command mention other bot ignored;
- command mention with arg processed;
- reply-to-bot processed;
- reply-to-non-bot ignored;
- empty mention helpful answer;
- worker group job uses `private=false` and `sendMessage`;
- Guest/Business tables не загрязняются group smoke.

## Security

Не выводились:

- Telegram token;
- Yandex/OpenRouter keys;
- Authorization headers;
- `ADMIN_API_TOKEN`;
- полный `ADMIN_TELEGRAM_IDS`;
- полный текст group/private сообщений;
- полные Telegram chat/user ids.

`.env` не добавлялся в git.
GitHub repo не создавался, push не выполнялся.
