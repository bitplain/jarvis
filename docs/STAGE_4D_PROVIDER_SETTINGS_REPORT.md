# Stage 4D Provider Settings Report

Verdict: `PASS_STAGE_4D_PROVIDER_SETTINGS_READY`

## Цель

Stage 4D добавляет admin-only Telegram настройки для выбора активного LLM-агента без изменения `.env` и без ручного изменения Railway Variables.

## Как открыть

- Команда `/settings`.
- Кнопка `Настройки` после `/start`.

## Варианты

- `Auto` — использовать env-based primary/fallback provider path.
- `Yandex` — принудительно использовать Yandex provider для следующих сообщений.
- `OpenRouter` — принудительно использовать OpenRouter provider для следующих сообщений.

## Где хранится выбор

Выбор хранится в PostgreSQL runtime setting `active_llm_provider` в таблице `runtime_settings`.

Если setting отсутствует, Jarvis использует `auto`.

Миграция таблицы выполняется автоматически: API service запускает `alembic upgrade head` перед стартом `uvicorn`. Ручной запуск миграции не должен быть обязательным для работы кнопки.

## Railway

Railway Variables всё равно нужны:

- `YANDEX_*` остаются в `jarvis-worker` variables.
- `OPENROUTER_*` остаются в `jarvis-worker` variables.

Кнопка меняет только runtime setting в PostgreSQL. Она не меняет Railway Variables и не печатает секреты.

Production deploy будет только после merge PR в `main`, успешного CI и Railway production autodeploy. PR Environments выключены.

## Known limitations

- Переключение влияет на следующие worker jobs, а не на уже начатую генерацию.
- Если выбранный provider не настроен, пользователь получит безопасную ошибку.
- Если кнопка нажата в коротком окне rollout до применения миграции, бот покажет безопасное сообщение о временной недоступности настроек вместо HTTP 500.
- Секреты не отображаются в Telegram UI, логах, документации или PR.

## Проверки

Локальная readiness-проверка без секретов:

```bash
uv run --python 3.12 --extra dev python scripts/smoke_provider_settings_readiness.py
```

Ожидаемый результат:

```text
PASS_PROVIDER_SETTINGS_READINESS
```
