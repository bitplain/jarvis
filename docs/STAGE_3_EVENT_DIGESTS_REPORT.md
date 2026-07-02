# Stage 3 Event Inbox Digests Report

## Verdict

`PASS_STAGE_3_EVENT_DIGESTS_READY` после локальной проверки ветки и draft PR flow.

## Что добавлено

- PostgreSQL table `digest_policies`.
- Default policies:
  - `personal_morning`: `06:50 Europe/Moscow`, scopes `personal`, `household`;
  - `work_start`: `09:00 Europe/Moscow`, scope `work`.
- `app/services/digests.py`: digest builder, renderer, schedule/grace logic.
- `/settings -> Дайджесты`: overview, per-policy screen, enable/disable, edit time, edit timezone, use current private chat, show now.
- `/digest`: admin-only status and show-now buttons.
- Worker cron `send_due_digests`.
- `/status` compact digest diagnostics.
- Readiness smoke `scripts/smoke_event_digest_readiness.py`.

## Scope separation

- Личный дайджест включает только `personal` и `household`.
- Личный дайджест не включает `work`, HelpDesk/tickets и `system`.
- Рабочий дайджест включает только `work`.
- Рабочий дайджест не включает `personal`, `household` и `system`.
- `system` events не включаются по умолчанию.

## Schedule safety

- Timezone default: `Europe/Moscow`.
- Grace window: 30 минут.
- `personal_morning` может отправиться с `06:50` до `07:20`.
- `work_start` может отправиться с `09:00` до `09:30`.
- Если worker проснулся после grace window, MVP пропускает digest до следующего локального дня и не отправляет backlog.

## Idempotency

- Worker ставит Redis claim до Telegram send:
  - `digest:send:{policy_key}:{local_date}`;
  - TTL: 36 часов.
- Duplicate claim пропускает отправку.
- `last_sent_date` и `last_sent_at` обновляются только после успешной Telegram отправки.
- При Telegram send failure claim удаляется, а policy остаётся retryable.

## Settings и access

- `/settings -> Дайджесты` доступен только env admin из `ADMIN_TELEGRAM_IDS`.
- Callback path access-gated тем же admin check.
- `target_chat_id` не угадывается.
- Если chat не настроен, scheduled worker не отправляет policy.
- `Использовать этот чат` работает только из личного чата администратора.
- Edit time принимает `HH:MM`.
- Edit timezone валидируется как IANA timezone.
- `/cancel` очищает digest FSM input.

## Telegram formatting

- Digest renderer использует Telegram HTML.
- Пользовательский текст экранируется через `html.escape`.
- Raw `payload_json`, `card_json` и JSON-like body не показываются.
- Ответ ограничен Telegram HTML limit.

## Out of scope

- WHOOP/OAuth пока не включён.
- HelpDesk migration в `event_items` не выполнялась.
- Railway Variables не менялись.
- Railway config/deploy/restart не выполнялись.
- IMAP destructive calls не выполнялись.
- HelpDesk emails не помечались read/seen, не удалялись, email replies не отправлялись.

## Verification

Команды verification перечислены в финальном ответе PR. Readiness marker:

```text
PASS_EVENT_DIGEST_READINESS
```
