# Stage 4: WHOOP OAuth + Raw Data Sync

Дата: 2026-07-02

## Итог

Stage 4 добавляет foundation для безопасного подключения WHOOP:

- OAuth authorization code flow через официальный WHOOP Developer API.
- Encrypted storage access/refresh tokens.
- Raw sync profile/sleep/recovery/cycle за последние 48 часов.
- Admin-only `/settings -> WHOOP`.
- Compact sanitized WHOOP block в `/status`.
- Optional worker cron `sync_whoop_integrations` каждые 30 минут.

## Официальный API

Используются только официальные WHOOP endpoints:

- Authorization URL: `https://api.prod.whoop.com/oauth/oauth2/auth`
- Token URL: `https://api.prod.whoop.com/oauth/oauth2/token`
- Profile: `GET https://api.prod.whoop.com/developer/v2/user/profile/basic`
- Sleep collection: `GET https://api.prod.whoop.com/developer/v2/activity/sleep`
- Recovery collection: `GET https://api.prod.whoop.com/developer/v2/recovery`
- Cycle collection: `GET https://api.prod.whoop.com/developer/v2/cycle`

Scopes:

```text
offline read:profile read:sleep read:recovery read:cycles
```

`offline` нужен для refresh token. Refresh сохраняет новый access token и новый refresh token, потому что WHOOP refresh token ротируется.

## Storage

Migration: `20260702_0018_whoop_oauth_sync`

Новые таблицы:

- `whoop_integrations`
- `whoop_sleep_records`
- `whoop_recovery_records`
- `whoop_cycle_records`

Tokens сохраняются только encrypted через `SecretCipher`/Fernet. Если `WHOOP_TOKEN_ENCRYPTION_KEY` отсутствует или невалиден, WHOOP считается не настроенным и OAuth storage не выполняется.

Raw records сохраняют исходный JSON WHOOP. `PENDING_SCORE` и `UNSCORABLE` сохраняются без ошибки, чтобы следующий sync мог обновить данные.

## Telegram UI

Раздел: `/settings -> WHOOP`

Действия:

- `Подключить WHOOP`
- `Синхронизировать сейчас`
- `Отключить`
- `Назад`

Connect flow:

1. Admin нажимает `Подключить WHOOP`.
2. Jarvis создаёт one-time Redis token `whoop:oauth:start:{token}` с TTL 10 минут.
3. Web start route consume-ит token, создаёт OAuth `state` с TTL 10 минут и redirect-ит в WHOOP.
4. Callback проверяет state, меняет code на tokens, получает profile и сохраняет integration.

`Отключить` переводит integration в `revoked` и очищает tokens; raw records сразу не удаляются.

## Worker

Worker job: `sync_whoop_integrations`

- Cron: каждые 30 минут.
- Skip if `WHOOP_ENABLED=false`.
- Skip if config incomplete.
- Skip if no connected integrations.
- Redis lock per integration: `whoop:sync:{integration_id}`.
- Manual sync button enqueue-ит тот же job.

429 WHOOP API обрабатывается как controlled rate limit без retry storm. 5xx превращается в controlled error. Errors пишутся в `last_error` без secrets/body/tokens.

## `/status`

WHOOP block показывает только:

- enabled/configured;
- connected integrations;
- last sync;
- last error count.

Tokens, client secret, encryption key, profile email и raw JSON в `/status` не выводятся.

## Required Manual Railway Variables

После merge вручную добавить/проверить в Railway UI:

- `WHOOP_ENABLED=true`
- `WHOOP_CLIENT_ID`
- `WHOOP_CLIENT_SECRET`
- `WHOOP_REDIRECT_URI=https://jarvis-production-786d.up.railway.app/integrations/whoop/oauth/callback`
- `WHOOP_TOKEN_ENCRYPTION_KEY`

Этот PR не меняет Railway Variables.

## Not Included

- AI-анализ сна.
- WHOOP card в личном утреннем дайджесте.
- Добавление WHOOP в scheduled digest.
- Создание WHOOP `event_items`.
- Private/reverse-engineered WHOOP API.
- HelpDesk migration.
- Deploy/redeploy/restart.

## Verification

```text
uv run --python 3.12 --extra dev ruff check .
uv run --python 3.12 --extra dev mypy app
uv run --python 3.12 --extra dev pytest -q
uv run --python 3.12 --extra dev python scripts/smoke_whoop_oauth_sync_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_railway_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_event_digest_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_status_household_context_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_telegram_update_idempotency_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_logging_hygiene_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_helpdesk_imap_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_helpdesk_ticket_workflow_readiness.py
uv run --python 3.12 --extra dev alembic heads
git diff --check
```
