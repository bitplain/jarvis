# Stage 4E Railway Migration Settings Fix Report

Verdict: `PASS_STAGE_4E_RAILWAY_MIGRATION_SETTINGS_FIX_READY`

## Root cause автомиграции

В production deploy logs для `jarvis-api` был виден старт Uvicorn и `/ready 200 OK`, но не было явного Alembic запуска. Это значит, что `railway.api.toml` или Railway UI Start Command не гарантировали выполнение миграции перед webhook runtime.

Риск: Railway UI Start Command может переопределить config-as-code. Если полагаться только на `railway.api.toml`, API может стать healthy со старой схемой PostgreSQL.

## Root cause кнопки

Telegram возвращает `TelegramBadRequest: message is not modified`, если callback пытается отредактировать сообщение тем же текстом и той же inline keyboard. Для settings callbacks это штатный idempotent сценарий, а не причина валить webhook HTTP 500.

## Что исправлено

- Добавлен code-level startup migration guard в API startup path.
- При `APP_ENV=production` API запускает `alembic upgrade head` до приёма webhook requests.
- Worker path не запускает migration helper.
- При ошибке миграции API startup падает, чтобы Railway deploy не стал healthy со старой схемой.
- `settings:refresh` безопасно обрабатывает `message is not modified`.
- Повторный выбор уже активного provider отвечает `Уже выбрано: ...` и не редактирует сообщение.
- `settings:close` пытается удалить сообщение, а если delete невозможен — редактирует его в `Настройки закрыты.` без inline keyboard.
- Неожиданные `TelegramBadRequest` логируются sanitized и возвращают безопасный callback answer.

## Как проверить после merge

- Railway API deploy logs должны содержать `startup_migrations_started` и `startup_migrations_completed`.
- `/settings` открывает меню настроек.
- Выбор `Yandex` и `OpenRouter` сохраняется.
- `Refresh` не даёт webhook 500.
- `Close` не даёт webhook 500.
- Обычный вопрос боту получает ответ.

## Проверки

```bash
uv run --python 3.12 --extra dev ruff check .
uv run --python 3.12 --extra dev mypy app
uv run --python 3.12 --extra dev pytest -q
uv run --python 3.12 --extra dev python scripts/smoke_provider_settings_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_railway_readiness.py
```
