# Stage 4G Lists And Reminders Report

## Scope

Stage 4G добавляет собственные списки покупок и напоминания для Jarvis. Telegram остаётся UI-слоем: обычные сообщения, Telegram HTML и inline buttons.

В PR не включены watcher, авто-чтение всех сообщений, Telegram Business checklists, native Telegram reminders и LLM parsing intent-ов.

## Supported Commands

Private chat:

- `добавь хлеб в список покупок`
- `добавь молоко, яйца, сыр в список`
- `покажи список покупок`
- `что купить?`
- `удали молоко из списка`
- `очисти купленное`
- `напомни завтра в 10 купить молоко`
- `напомни через 30 минут проверить духовку`
- `напомни 28.06 в 14:00 оплатить счёт`
- `покажи напоминания`

Group/supergroup:

- `@bot_username добавь хлеб в список покупок`
- `@bot_username покажи список покупок`
- `@bot_username напомни завтра в 9 купить памперсы`
- `@bot_username покажи напоминания`

Group команды обрабатываются только через существующую mention/reply gating и access policy.

## Storage

Migration: `20260626_0008_lists_reminders`.

Таблицы:

- `shopping_lists`
- `shopping_list_items`
- `reminders`

Private list scoped по user id. Group list scoped по group chat id. Напоминания хранят `remind_at` в UTC.

## Formatting

Ответы списков и напоминаний используют Telegram HTML (`parse_mode="HTML"`). Пользовательский текст всегда проходит через `html.escape`; raw MarkdownV2 не используется.

Inline button labels остаются plain text. Callback data короткие: `shop:*` и `rem:*`.

## Reminder Timezone

Parser использует `Europe/Moscow` как default timezone, если другой timezone не передан явно в коде. В PostgreSQL сохраняется UTC.

Stage 4G-1 добавляет runtime setting `lists.timezone` через `/settings -> Списки и напоминания`. Значение валидируется как IANA timezone через `zoneinfo.ZoneInfo`, влияет на parsing/display и не меняет UTC-хранение.

## Worker Delivery

`deliver_due_reminders` подключён к arq worker и cron tick каждые 30 секунд. Worker отправляет due reminder как HTML message с display time в `lists.timezone` и помечает запись `sent` только после успешного Telegram send.

Sanitized log events:

- `reminder_due_delivery_started`
- `reminder_due_delivery_sent`
- `reminder_due_delivery_failed`

Текст напоминаний в logs не пишется.

## Not Included

- watcher;
- авто-чтение всех сообщений;
- Telegram Business checklists;
- native Telegram reminders;
- LLM parsing;
- изменение Railway Variables;
- Telegram Business integration.

## Verification

Primary readiness:

```bash
uv run --python 3.12 --extra dev python scripts/smoke_lists_reminders_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_lists_reminders_ux_readiness.py
```

Expected verdict:

```text
PASS_LISTS_REMINDERS_READINESS
PASS_LISTS_REMINDERS_UX_READINESS
```
