# Stage 1A/2A Structured Rich Cards + Event Inbox Foundation

## Summary

Stage 1A/2A добавляет базу Event Center без WHOOP OAuth/sync, AI-анализа сна, digest scheduling, production deploy и Railway config changes.

## Data model

Новая таблица: `event_items`.

Поля:

- `id`
- `user_id`
- `chat_id`
- `scope`
- `event_type`
- `title`
- `body`
- `priority`
- `status`
- `source`
- `payload_json`
- `card_json`
- `due_at`
- `created_at`
- `updated_at`

Поддерживаемые значения:

- scope: `personal`, `household`, `work`, `system`;
- status: `new`, `seen`, `done`, `snoozed`, `archived`, `failed`;
- priority: `low`, `normal`, `high`, `critical`;
- event type: `reminder`, `note`, `shopping`, `helpdesk_ticket`, `whoop_sleep`, `system_alert`, `digest_item`.

## Structured cards

`card_json` хранит минимальную карточку:

```json
{
  "type": "reminder",
  "title": "Напоминание",
  "severity": "info",
  "facts": [
    {"label": "Когда", "value": "Сегодня"}
  ],
  "summary": "Текст напоминания",
  "actions": [
    {"id": "done", "label": "Готово"},
    {"id": "snooze", "label": "Позже"}
  ]
}
```

Telegram renderer:

- экранирует HTML;
- не падает на пустых `facts`/`actions`;
- использует fallback для отсутствующей или повреждённой карточки;
- не показывает пользователю raw JSON.

## Commands

- `/inbox` показывает active `personal` + `household` events.
- `/work` показывает active `work` events.

`system` events скрыты по умолчанию. HelpDesk/tickets относятся к `work` и не должны попадать в `/inbox`.

MVP сортировка: priority desc, `due_at` asc/nulls last, `created_at` desc. Лимит выдачи: 10 событий.

## Callbacks

Renderer формирует callback data в формате `event:<action>:<event_id>` для:

- `done`
- `snooze`
- `details`

Callback data не содержит пользовательский текст, JSON, prompts, URLs, tokens или env secrets.

## Timezone

Будущая default digest timezone зафиксирована как `Europe/Moscow`.

Digest scheduling в Stage 1A/2A не реализован.

## Out of scope

- WHOOP OAuth;
- WHOOP sync;
- AI-анализ сна;
- digest scheduling;
- HelpDesk migration в `event_items`;
- production deploy;
- Railway Variables/config changes;
- merge в `main`.

## Verification

```bash
uv run --python 3.12 --extra dev pytest tests/test_event_cards.py tests/test_event_items.py tests/test_event_inbox_router.py -q
uv run --python 3.12 --extra dev ruff check .
uv run --python 3.12 --extra dev mypy app
uv run --python 3.12 --extra dev pytest -q
```
