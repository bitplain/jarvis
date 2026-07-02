# Stage 5: WHOOP card в личный inbox + утренний digest

## Verdict

`PASS_STAGE_5_WHOOP_DIGEST_CARD_READY`

Stage 5 добавляет personal-only WHOOP sleep/recovery card из уже
синхронизированных raw WHOOP records. Карточка создаётся через `event_items` и
попадает в `/inbox` и personal morning digest без отдельного WHOOP digest logic.

## Что реализовано

- Новый сервис `app/services/whoop_cards.py`.
- После successful raw sync `WhoopSyncService` вызывает `upsert_latest_whoop_sleep_event`.
- Event contract:
  - `scope=personal`;
  - `event_type=whoop_sleep`;
  - `source=whoop`.
- Idempotency key: `whoop_sleep:<integration_id>:<sleep_id>` в `payload_json.identity_key`.
- Повторный sync обновляет существующий event, не создавая дубль.
- Pending -> scored обновляет ту же карточку.
- Если event уже `done`, статус не возвращается в `new`.

## Scope

WHOOP card отображается только в personal контуре:

- `/inbox`: visible.
- personal morning digest: included.
- `/work`: excluded.
- work digest: excluded.

Work digest не менялся: он по-прежнему берёт только `scope=work`.

## Data Source

Источник данных — только уже сохранённые таблицы:

- `whoop_sleep_records`;
- `whoop_recovery_records`.

Stage 5 не вызывает live WHOOP OAuth/API при построении карточки и не использует
private/reverse-engineered WHOOP API.

## Card Logic

Выбор sleep:

1. Последний `SCORED` non-nap sleep за последние 72 часа.
2. Если scored нет, последний `PENDING_SCORE` non-nap sleep.
3. Если есть только `UNSCORABLE`, safe technical card.

Facts:

- `Сон`;
- `Recovery`;
- `HRV`;
- `RHR`;
- `Score`.

Отсутствующие значения отображаются как `нет данных`. Raw JSON не копируется в
`card_json`, `body` или Telegram-rendered text.

## Safety

- No AI analysis.
- No medical advice.
- Нет диагнозов, лечения или медицинских выводов.
- Нет отдельной команды `/whoop`.
- Нет изменений Railway Variables.
- Нет deploy/redeploy/restart.
- Нет HelpDesk migration.
- Telegram HTML safety остаётся на существующем Structured Rich Card renderer.

## Stage 6

Stage 6 может добавить optional AI sleep insight отдельным PR после отдельного
safety review. Stage 5 намеренно оставляет AI sleep analysis вне scope.

## Verification

Плановый verification bundle:

```bash
uv run --python 3.12 --extra dev ruff check .
uv run --python 3.12 --extra dev mypy app
uv run --python 3.12 --extra dev pytest -q
uv run --python 3.12 --extra dev python scripts/smoke_whoop_digest_card_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_whoop_oauth_sync_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_event_digest_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_railway_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_status_household_context_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_telegram_update_idempotency_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_logging_hygiene_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_helpdesk_imap_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_helpdesk_ticket_workflow_readiness.py
uv run --python 3.12 --extra dev alembic heads
git diff --check
git status --short --branch
```
