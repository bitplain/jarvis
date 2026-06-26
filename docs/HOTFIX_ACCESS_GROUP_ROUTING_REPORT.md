# Hotfix Access Group Routing Report

## Статус

Ветка: `codex/hotfix-access-settings-add-status`

Draft PR #11 обновляется без создания нового PR.

Expected verdict: `PASS_HOTFIX_ACCESS_GROUP_ROUTING_READY`

## Production symptom

В PostgreSQL должны быть разрешены:

- user `291844566`
- user `5117224471`
- group `-5437860232`

В разрешённой группе сообщение `@Home_ai_my_bot привет` от обычного allowed user молчало, а env admin в той же группе получал ответ. Правильная команда `/whoami` тоже не дала полезный диагностический ответ.

## Root cause

Расследование через webhook/dispatcher tests показало два независимых факта.

1. Group routing в текущем коде уже использовал `message.from_user.id` для пользователя и signed `message.chat.id` для группы. Production-like regression `user_id=291844566`, `chat_id=-5437860232`, `text="@Home_ai_my_bot привет"` проходит через middleware, group handler и создаёт ровно одну `process_llm_message`.
2. В текущей ветке PR #11 был сломан `TelegramAccessRepository.upsert_entry()` в `app/db/repositories/telegram_access.py`: PostgreSQL `on_conflict_do_update()` строился без `set_`, поэтому SQLAlchemy падал с `ValueError` ещё до выполнения запроса. Это ломало надёжное сохранение access-записей через `/settings -> Доступ`.

Дополнительно `/whoami` в `app/bot/routers/commands.py` был слишком слабым диагностическим ответом: он показывал ID, но не показывал allowlist-статус текущего пользователя и текущей группы. Команда не вызывала LLM и не должна была создавать job, но её формат не позволял быстро проверить точные production IDs.

## Почему admin отвечал, а allowed user молчал

Env admin проходит `AdminAccessMiddleware.__call__()` до DB allowlist: `ADMIN_TELEGRAM_IDS` является главным bypass для доступа.

Allowed user зависит от PostgreSQL allowlist. Если запись не была фактически сохранена или group ID не совпал с signed `chat.id`, middleware молча отсекает group update как `deny_silent`, чтобы бот не писал `Доступ запрещён` в группе.

## Почему `/whoami` был усилен

`/whoami` теперь остаётся строго ограниченным bypass только для этой команды и показывает:

```text
Ваш Telegram user ID: <user_id>
Тип чата: private/group/supergroup
Telegram chat ID: <chat_id>
```

В group/supergroup дополнительно показывается статус только текущих IDs:

```text
Пользователь разрешён: да/нет
Группа разрешена: да/нет
```

Команда не добавляет пользователя, не раскрывает списки, не вызывает LLM и не создаёт worker job.

## Исправленная access policy

- Admin может обращаться к боту в группе через mention/reply.
- DB allowed user может обращаться к боту в allowed group через mention/reply.
- Unknown group user остаётся silent, кроме `/whoami`.
- Allowed user в disallowed group остаётся silent, если group allowlist непустой.
- Group message без mention/reply игнорируется до LLM/job независимо от доступа.
- Если список разрешённых групп пустой, сохраняется прежняя семантика: authorized user mention/reply работает в любой группе.

## Diagnostics

Добавлено sanitized событие `telegram_access_decision`.

Поля:

- `chat_type`
- `chat_id`
- `user_id`
- `is_admin`
- `is_user_allowed`
- `has_group_allowlist`
- `is_group_allowed`
- `is_mention_or_reply`
- `decision`
- `reason`

IDs маскируются. Текст сообщений, labels, tokens, headers, prompts и полный Telegram update не логируются.

## Tests

Добавлены webhook-level regression tests:

- `test_unknown_private_user_whoami_bypasses_access`
- `test_unknown_group_user_whoami_bypasses_access`
- `test_whoami_does_not_enqueue_llm_job`
- `test_allowed_user_in_allowed_group_mention_enqueues_once`
- `test_allowed_user_in_allowed_group_reply_enqueues_once`
- `test_allowed_user_without_mention_is_ignored`
- `test_unknown_user_in_allowed_group_is_silent`
- `test_allowed_user_in_disallowed_group_is_silent`
- `test_group_access_uses_from_user_id`
- `test_group_access_uses_signed_chat_id`
- `test_access_db_error_denies_safely`

Добавлен repository regression:

- `test_repository_upsert_entry_builds_conflict_update_statement`

## Smoke

Добавлен:

```bash
uv run --python 3.12 --extra dev python scripts/smoke_access_group_routing_readiness.py
```

Ожидаемый verdict:

```text
PASS_ACCESS_GROUP_ROUTING_READINESS
```

## Live checklist

1. Обычный пользователь отправляет `/whoami` в группе.
2. Проверяется его точный user_id.
3. Проверяется точный отрицательный chat_id.
4. Оба ID добавляются через `/settings -> Доступ`.
5. Пользователь отправляет `@Home_ai_my_bot привет`.
6. Бот отвечает ровно один раз.
7. Неизвестный пользователь с mention остаётся без ответа.
8. Worker получает ровно одну job.
