# Stage 4G-1 Lists And Reminders UX Report

## Scope

Stage 4G-1 улучшает UX списков покупок и напоминаний после Stage 4G без изменения основной архитектуры хранения и worker delivery.

Включено:

- `/settings -> Списки и напоминания`;
- runtime setting `lists.timezone`;
- HTML help для списков и напоминаний;
- FSM add-flow для shopping list и reminders;
- inline buttons для add, clear, done, snooze и delete;
- readiness smoke `scripts/smoke_lists_reminders_ux_readiness.py`.

Не включено:

- watcher;
- voice/transcription;
- Telegram Business integration;
- Telegram Business checklists;
- Railway Variables changes;
- PR #5 changes.

## Settings Path

Раздел доступен через admin-only `/settings`:

```text
/settings -> Списки и напоминания
```

Экран показывает текущий timezone, help, личные active reminders и личный shopping list.

Timezone хранится в PostgreSQL `runtime_settings`:

```text
key: lists.timezone
default: Europe/Moscow
```

Ввод timezone принимает только IANA timezone, валидированный через `zoneinfo.ZoneInfo`. Invalid value отклоняется понятным русским сообщением. `/cancel` очищает FSM state и не меняет сохранённое значение.

## Timezone Behavior

`lists.timezone` влияет на:

- parsing reminders (`напомни завтра в 10 ...`);
- display created reminder;
- display active reminders list;
- due reminder delivery message.

Storage остаётся UTC: `reminders.remind_at` не меняет контракт Stage 4G.

## Commands And Help

Private help triggers:

- `помощь список`
- `помощь напоминания`
- `как пользоваться списком`
- `как пользоваться напоминаниями`

Private examples:

- `добавь хлеб в список покупок`
- `добавь молоко, яйца, сыр в список`
- `покажи список покупок`
- `удали молоко из списка`
- `напомни через 30 минут проверить духовку`
- `напомни завтра в 10 купить молоко`
- `напомни 28.06 в 14:00 оплатить счёт`
- `покажи напоминания`

Group/supergroup examples require explicit mention/reply:

- `@Home_ai_my_bot добавь хлеб в список покупок`
- `@Home_ai_my_bot покажи список покупок`
- `@Home_ai_my_bot напомни завтра в 9 купить памперсы`

Help messages use Telegram HTML and do not enqueue LLM jobs.

## Button UX

Shopping list:

- `➕ Добавить` starts FSM input and accepts one or more items separated by comma;
- `✅ Очистить купленное` removes done items;
- `🧹 Очистить всё` asks confirmation before deleting active and done items;
- item buttons still support done, restore and delete.

Reminders:

- active list shows `✅ Выполнено`, `⏰ +10 мин`, `⏰ +1 час`, `🗑 Удалить`;
- `➕ Добавить напоминание` starts FSM input and reuses the deterministic parser;
- repeated done/delete clicks are safe.

Callback data stays short and does not include user text.

## Verification

Primary checks:

```bash
uv run --python 3.12 --extra dev ruff check .
uv run --python 3.12 --extra dev mypy app
uv run --python 3.12 --extra dev pytest -q
uv run --python 3.12 --extra dev python scripts/smoke_lists_reminders_ux_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_lists_reminders_readiness.py
```

Expected verdict:

```text
PASS_LISTS_REMINDERS_UX_READINESS
PASS_LISTS_REMINDERS_READINESS
```

## Live Checklist

- `/settings -> Списки и напоминания`;
- set timezone;
- invalid timezone rejected;
- shopping add via button;
- shopping clear all confirmation;
- reminder add via button;
- reminder list/snooze/delete;
- private LLM still works;
- group mention still works;
- watcher still not enabled.
