# Stage 4L HelpDesk IMAP Inbox Report

## Цель

Реализован узкий MVP: один HelpDesk IMAP mailbox, polling worker, deterministic parsing GLPI/helpdesk писем, Telegram HTML карточка заявки, дедупликация и `/status` diagnostics.

## Railway Variables

Значения добавляются пользователем вручную после merge PR. Код, тесты и PR не меняют Railway Variables.

```env
HELPDESK_IMAP_ENABLED=true
HELPDESK_IMAP_HOST=imap.example.ru
HELPDESK_IMAP_PORT=993
HELPDESK_IMAP_SSL=true
HELPDESK_IMAP_USERNAME=...
HELPDESK_IMAP_PASSWORD=...
HELPDESK_IMAP_FOLDER=INBOX
HELPDESK_IMAP_POLL_INTERVAL_SECONDS=120
HELPDESK_IMAP_FROM_FILTER=sd@asdf.help
HELPDESK_IMAP_SUBJECT_PREFIX=[GLPI #
HELPDESK_TELEGRAM_CHAT_ID=...
HELPDESK_MARK_SEEN=false
```

IMAP password вводится только через `.env`/Railway Variables: без Telegram-ввода пароля.

## Поведение

- `HELPDESK_IMAP_ENABLED=false`: worker job no-op.
- Enabled, но config incomplete: sanitized warning, без crash loop.
- Worker cron: `check_helpdesk_imap_mailbox` раз в минуту, внутри throttle по `HELPDESK_IMAP_POLL_INTERVAL_SECONDS`.
- IMAP: stdlib `imaplib`, SSL true/false, `select` readonly по умолчанию, `BODY.PEEK[]`.
- Mark seen: выключен по умолчанию. Если включён, `Seen` ставится только после успешной Telegram notification.

## GLPI parsing

Parser best-effort извлекает:

- ticket id;
- `new_ticket` / `comment` / `unknown`;
- ticket URL;
- title;
- description;
- employee full name;
- position;
- manager;
- start date;
- access items;
- comment/task counts;
- masked sender email;
- clipped sanitized raw excerpt.

LLM не используется.

## Telegram карточка

Карточка отправляется как Telegram HTML.
Весь текст из письма экранируется через `html.escape`.
Кнопка `Открыть заявку` добавляется только для safe `http/https` URL.
Reminder/hide buttons не входят в MVP.

## Dedup/status

Таблица: `helpdesk_email_events`.

Дедупликация:

- partial unique `message_id`;
- partial unique `(folder, imap_uid)`.

`/status` показывает HelpDesk IMAP section без live IMAP connect:

- enabled/configured;
- host configured/missing;
- masked username;
- folder;
- last check;
- last success;
- last error;
- processed last 24h;
- pending notifications.

## Ограничения

- один mailbox only;
- нет email replies;
- нет удаления писем;
- нет mark-seen по умолчанию;
- нет OCR/RAG;
- нет multi-mailbox UI;
- нет Smart Watcher;
- нет live destructive Telegram calls.

## Live checklist

1. Добавить Railway Variables в `jarvis-worker`.
2. Deploy после merge в `main`.
3. Проверить `/status`: HelpDesk IMAP enabled/configured, last error `none` или ожидаемый sanitized status.
4. Дождаться или отправить GLPI письмо от `HELPDESK_IMAP_FROM_FILTER`.
5. Проверить Telegram карточку заявки в `HELPDESK_TELEGRAM_CHAT_ID`.
6. Дождаться следующего polling interval и проверить, что duplicate card не пришла.
7. При `HELPDESK_MARK_SEEN=false` проверить, что письмо осталось unread.

## Readiness

```bash
uv run --python 3.12 --extra dev python scripts/smoke_helpdesk_imap_readiness.py
```

Ожидаемый verdict:

```text
PASS_HELPDESK_IMAP_READINESS
```
