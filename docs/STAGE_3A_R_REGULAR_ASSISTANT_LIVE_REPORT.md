# Stage 3A-R Regular Assistant Live Smoke Report

Дата: 2026-06-14

Стартовый commit: `3413731 Stage 3A-R: clarify regular assistant modes`

## Итог

Verdict: `PASS_STAGE_3A_R_GROUP_ROUTING_READY`

Regular Assistant live smoke через polling подтвердил private chat, context commands после исправления, forwarded/draft/reset manual flow и Guest/Business isolation checks. Первичный group smoke был partial, но Stage 3A-R-GROUP повторно проверил настоящий Telegram group/supergroup path и подтвердил group rows, worker job `private=false` и ответ в группе.

Подробный group routing отчёт:

- `docs/STAGE_3A_R_GROUP_ROUTING_REPORT.md`

## Readiness

Выполнено до live runner:

- `scripts/smoke_regular_readiness.py`: `PASS_REGULAR_READINESS`
- `scripts/smoke_polling_readiness.py`: `PASS_POLLING_READINESS`
- `scripts/smoke_llm.py`: `PASS_LLM_SMOKE`

Sanitized status:

- Telegram token: `SET`
- `ADMIN_TELEGRAM_IDS`: `SET count=1`
- Yandex model: `SET`
- OpenRouter model: `SET`
- Postgres: `OK`
- Redis: `OK`
- Business Mode: optional/disabled

В readiness smoke был виден fallback primary LLM, но итоговый LLM smoke прошёл: Yandex и OpenRouter доступны. В live polling stdout для проверенных command/guest paths были HTTP 200 от provider без вывода ключей.

## Runtime

Перед polling:

- `docker compose up -d`: containers running
- `docker compose ps`: `api` healthy, `postgres` healthy, `redis` healthy, `worker` running
- `docker compose exec api alembic upgrade head`: OK
- `curl /health`: `{"status":"ok"}`
- `curl /ready`: `{"status":"ok","checks":{"postgres":true,"redis":true}}`

## Polling Runner

`scripts/run_polling.py` запускался без webhook/tunnel.

Startup evidence:

- `polling started`
- allowed updates: `business_connection`, `business_message`, `edited_business_message`, `deleted_business_messages`, `guest_message`, `message`, `edited_message`, `callback_query`
- guest mode: enabled
- admin-only: enabled
- business mode: disabled
- business reply: disabled
- admin ids: `SET count=1`
- polling started for bot username from env

Webhook deletion:

- readiness script подтвердил `delete_webhook: OK drop_pending_updates=false`
- polling runner выполнял `delete_webhook(drop_pending_updates=false)` без ошибки

Runner перезапускался после кодовых фиксов, чтобы live repeat шёл уже на новой версии кода.

## Manual Telegram Scenarios

| Сценарий | Результат | Evidence |
| --- | --- | --- |
| Private text | PASS | polling update handled; worker log показал private `process_llm_message` job; пользователь получил ответ |
| `/summary` | PASS | live ответ был получен в Telegram |
| `/translate` | FIXED_AND_PASS | сначала команда использовала старую memory вместо inline argument; после фикса live repeat пользователем подтверждён как корректный |
| `/factcheck` | FIXED_AND_PASS | сначала команда не проверяла inline fact; после фикса live repeat пользователем подтверждён как корректный |
| Draft reply | PASS_MANUAL | пользователь выполнил сценарий и написал `готово`; отдельный приватный текст в отчёт не выводится |
| Forwarded message assistant | PASS_MANUAL | пользователь выполнил сценарий и написал `готово`; приватный текст не выводится |
| `/reset` | PASS | после reset таблица `messages` была пуста, что подтверждает очистку regular memory текущего чата |
| Group plain without mention/reply | PASS | update был обработан быстро; `messages` не пополнилась, worker job не создан, guest rows не выросли |
| Group mention | PASS_AFTER_STAGE_3A_R_GROUP | повторный group smoke подтвердил обычный group/supergroup update, worker job `private=false`, group DB rows и ответ в группе |
| Group reply | PASS_AFTER_STAGE_3A_R_GROUP | повторный group smoke подтвердил group routing path и ручное выполнение reply-сценария |

## Найденные ошибки и исправления

### Context commands ignored inline arguments

Симптом:

- `/translate <text>` использовал старый сохранённый контекст вместо текста после команды.
- `/factcheck <text>` не проверял переданный inline fact.

Root cause:

- `_handle_context_command` всегда строил context из `MemoryService.recent_messages()` и не читал `message.text` после `/command`.

Fix:

- добавлен `_command_argument()`;
- inline argument имеет приоритет над saved memory;
- поддержана форма `/command@bot_username`;
- при пустом аргументе остаётся fallback на сохранённый контекст;
- prompt `/translate` больше не принуждает переводить только на русский, а учитывает целевой язык из запроса.

Regression tests:

- `tests/test_context_commands.py`

### Group handler was a placeholder

Симптом:

- group handler отвечал заглушкой, но не сохранял message и не ставил worker job.

Root cause:

- `handle_group_message` завершался `message.answer("Групповой ответ будет подготовлен через worker.")` без memory/redis path.

Fix:

- для group mention/reply сохраняется user message в regular memory группы;
- создаётся `process_llm_message` job с `private=false`;
- plain group messages без mention/reply остаются ignored без DB/LLM.

Regression tests:

- `tests/test_group_handler.py`

### Private router could catch group messages before group router

Симптом:

- `private.build_router()` регистрировал catch-all `router.message()` раньше `groups.build_router()`.

Root cause:

- private/group routers не имели chat type filters, порядок dispatcher мог мешать group router.

Fix:

- private router получил filter `F.chat.type == "private"`;
- group router получил filter `F.chat.type.in_({"group", "supergroup"})`;
- добавлен dispatcher regression test на наличие chat type filters.

Regression tests:

- `tests/test_dispatcher.py`

## DB Persistence / Isolation

PostgreSQL checks выполнялись без вывода полного текста сообщений и полных Telegram IDs.

Facts:

- worker logs подтвердили private `process_llm_message` jobs.
- после `/reset` regular table `messages` временно вернула `0 rows`, что подтвердило очистку regular memory текущего чата.
- повторный Stage 3A-R-GROUP smoke создал group USER и group ASSISTANT rows.
- group plain ignored не создал лишний LLM job/regular memory row.
- group mention/reply подтвердили group routing path; worker log показал job `private=false`.
- `guest_messages_stub`: rows present; recent rows выросли во время первых попыток, которые фактически были `guest_message`, а не group assistant. После изменения privacy/settings новые попытки guest rows не увеличили.
- `business_messages`: `0 rows`, contamination from regular smoke не обнаружена.

Ограничение проверки:

- из-за `/reset` одна DB snapshot не может одновременно показать historical private user/assistant rows и очищенную память; live worker logs и Telegram manual result использованы как evidence обработки private flow, а пустая `messages` сразу после reset — как evidence очистки.

## Security

Не выводились:

- Telegram token;
- Yandex/OpenRouter keys;
- Authorization headers;
- `ADMIN_API_TOKEN`;
- полный `ADMIN_TELEGRAM_IDS`;
- полный приватный текст сообщений в отчёте.

`.env` не добавлялся в git.

GitHub repo не создавался, push не выполнялся.

## Финальный Verdict

`PASS_STAGE_3A_R_GROUP_ROUTING_READY`

Причина: private/command/draft/forwarded/reset paths прошли или были исправлены и повторно подтверждены. Повторный Stage 3A-R-GROUP smoke подтвердил настоящий group/supergroup path с sanitized diagnostics, DB memory rows, worker job `private=false` и ответом в группе.
