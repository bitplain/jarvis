# Stage 4L-2 HelpDesk Ticket Workflow Report

## Итог

Stage 4L-2 добавляет workflow заявок GLPI поверх Stage 4L HelpDesk IMAP Inbox.

Новая заявка создаёт work item `waiting_ack`, Telegram карточка получает кнопку `В работу`, а worker reminder path напоминает каждые 10 минут до взятия в работу. После `В работу` заявка становится `in_work`, показывается в `/ticket`, получает кнопки `Готово` и `Отложить 1ч`, а reminder interval становится 30 минут. `Готово` переводит заявку в `done` и останавливает reminders.

Команда только одна: `/ticket`. Алиас `/tiket` не добавлен и не закрепляется как API.

## Data model

Добавлена таблица `helpdesk_ticket_work_items`:

- `id uuid pk`;
- `glpi_ticket_id text not null`;
- `latest_event_id uuid nullable references helpdesk_email_events(id)`;
- `title text not null`;
- `status text not null`: `waiting_ack`, `in_work`, `done`, `dismissed`;
- `telegram_chat_id bigint not null`;
- `assigned_by_user_id bigint nullable`;
- `assigned_at timestamptz nullable`;
- `done_at timestamptz nullable`;
- `next_reminder_at timestamptz nullable`;
- `last_reminded_at timestamptz nullable`;
- `reminder_interval_minutes integer not null`;
- `created_at timestamptz not null`;
- `updated_at timestamptz not null`.

Unique key: `(glpi_ticket_id, telegram_chat_id)`.

## Runtime flow

1. `HelpdeskImapService` сохраняет `helpdesk_email_events`.
2. Для `new_ticket` с GLPI id создаёт/обновляет `helpdesk_ticket_work_items`.
3. Карточка новой заявки получает кнопку `В работу` с callback `hd_ticket:take:<id>`.
4. `helpdesk_tickets` router обрабатывает `/ticket` и callbacks `hd_ticket:*`.
5. Worker cron `remind_helpdesk_tickets` отправляет due reminders и использует Redis claim `helpdesk_ticket:reminder:<id>`.

Если Telegram send падает, `next_reminder_at` не продвигается. Следующий cron сможет повторить отправку.

## Safety

- IMAP чтение остаётся read-only через `BODY.PEEK[]`.
- Email replies не добавлены.
- Удаление писем не добавлено.
- Mark-seen поведение Stage 4L не расширено: по умолчанию `HELPDESK_MARK_SEEN=false`.
- Внутренняя ticket URL button не добавлена.
- Railway Variables не меняются из кода или PR.
- Callback access-gated: admin или DB allowed user, плюс совпадение Telegram chat с work item.
- Все email-derived поля в Telegram HTML проходят escaping.
- Logs не содержат raw email body, title/body в callback data, token/password/API key/header.

## Readiness

Новый smoke:

```bash
uv run --python 3.12 --extra dev python scripts/smoke_helpdesk_ticket_workflow_readiness.py
```

Ожидаемый verdict:

```text
PASS_HELPDESK_TICKET_WORKFLOW_READINESS
```

## Self-audit

TICKET_STATE_SAFETY: PASS

`done` не переоткрывается при повторном письме с тем же `glpi_ticket_id`; unique `(glpi_ticket_id, telegram_chat_id)` не даёт duplicate work item.

REMINDER_IDEMPOTENCY: PASS

`remind_helpdesk_tickets` использует Redis claim `helpdesk_ticket:reminder:<id>`, а `next_reminder_at` двигается только после успешной Telegram отправки.

CALLBACK_ACCESS_SAFETY: PASS

Callbacks `hd_ticket:*` отдельно проверяют admin/allowed user и совпадение chat id, потому что callback query не покрывается message middleware.

NO_EMAIL_DESTRUCTIVE_ACTIONS: PASS

Stage 4L-2 не добавляет IMAP delete, email replies или новые mark-seen paths.

TELEGRAM_FORMATTING_SAFETY: PASS

Telegram HTML форматируется через `html.escape`; callback data содержит только short id/action/minutes.

REGRESSION_CHECKS: PASS

Покрытие добавлено для service, formatter, IMAP integration, router, worker cron и readiness smoke.

## Live checklist

1. Deploy происходит только после manual merge в `main`.
2. Railway Variables не менять в рамках PR.
3. Убедиться, что Stage 4L HelpDesk IMAP уже настроен и `/status` показывает configured/baseline.
4. Получить новую GLPI заявку в `HELPDESK_TELEGRAM_CHAT_ID`.
5. Проверить карточку с кнопкой `В работу`.
6. Не нажимать `В работу` 10 минут и проверить reminder `Новая заявка GLPI #... ещё не взята в работу.`.
7. Нажать `В работу`.
8. Выполнить `/ticket` и проверить заявку в списке in-work.
9. Нажать `Отложить 1ч` и проверить перенос следующего reminder.
10. Нажать `Готово` и убедиться, что reminders больше не приходят.
