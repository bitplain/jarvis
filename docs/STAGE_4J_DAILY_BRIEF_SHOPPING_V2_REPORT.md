# Stage 4J Daily Brief + Shopping v2 Report

## Verdict

`PASS_STAGE_4J_DAILY_BRIEF_SHOPPING_V2_READY` после локальных unit/static readiness checks.

## Что добавлено

- Daily Brief команды: `сводка`, `сводка дня`, `что сегодня?`.
- `/settings -> Сводка дня`: enabled, время `HH:MM`, timezone IANA, `Показать сейчас`.
- Scheduled private auto-brief через arq job `deliver_daily_briefs`.
- PostgreSQL migration `20260627_0010`: nullable Shopping v2 поля и таблица `daily_brief_settings`.
- Shopping v2 parser: quantity/unit, note и простые категории.
- Grouped shopping display по категориям с Telegram HTML escaping.

## Поведение Daily Brief

- Private brief использует private scope пользователя.
- Group brief работает только по явной group mention/reply и не включает auto-send.
- Auto-brief проверяется worker cron раз в минуту.
- `last_sent_date` хранит локальную дату последней успешной отправки и не даёт отправить brief дважды в тот же день.
- Если Telegram send падает, `last_sent_date` не обновляется; лог остаётся sanitized.

## Shopping v2

`shopping_list_items` расширен nullable-полями:

- `quantity numeric`
- `unit text`
- `note text`
- `category text`

Старые items без этих полей остаются валидными.

Поддержанные примеры:

- `молоко 2 шт`
- `яблоки 1 кг`
- `памперсы размер 4`
- `молоко 2.5% 2 бутылки`

Категории определяются простыми правилами: `Молочка`, `Хлеб`, `Ребёнок`, `Мясо`, `Овощи`, `Фрукты`, иначе `Другое`.

## Non-goals

- Watcher не включался.
- Voice/transcription/media не добавлялись.
- Telegram Business не менялся.
- Auto-reading group messages не добавлялся.
- Railway Variables не менялись.
- Push/merge в `main` не выполнялся.

## Локальные проверки

```bash
uv run --python 3.12 --extra dev ruff check app tests/test_daily_brief_service.py tests/test_shopping_service.py tests/test_telegram_formatting.py tests/test_settings_command.py tests/test_worker_jobs.py
uv run --python 3.12 --extra dev mypy app
uv run --python 3.12 --extra dev pytest tests/test_shopping_service.py tests/test_telegram_formatting.py tests/test_daily_brief_service.py tests/test_settings_command.py::test_settings_home_contains_daily_brief_section tests/test_settings_command.py::test_render_daily_brief_settings_text tests/test_worker_jobs.py::test_daily_brief_worker_is_registered -q
uv run --python 3.12 --extra dev python scripts/smoke_daily_brief_shopping_v2_readiness.py
```

## Live checklist после merge/deploy

1. Открыть `/settings -> Сводка дня`.
2. Поставить время brief.
3. Включить brief.
4. Отправить `сводка`.
5. Добавить `молоко 2 шт`.
6. Добавить `памперсы размер 4`.
7. Проверить группировку списка по категориям.
8. Дождаться scheduled brief и убедиться, что он отправился один раз за день.
9. Проверить, что reminders/lists/memory/status продолжают работать.

## Remote AGENTS sync

Серверные/live project paths в этом репозитории не заведены.

`remote AGENTS sync = N/A until server/live paths exist`
