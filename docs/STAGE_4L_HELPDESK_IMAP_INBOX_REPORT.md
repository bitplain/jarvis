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
- First-run baseline: первый успешный poll без mailbox state сохраняет текущий max UID и не отправляет старые письма из INBOX.
- Subsequent poll: worker читает только `UID last_seen_uid+1:*`; новый комментарий по старой заявке приходит как новое email message с новым UID и отправляется.
- UIDVALIDITY reset: при смене `UIDVALIDITY` worker ставит новый baseline на current max UID и не рассылает старый mailbox заново.
- Manual baseline: admin-only `/helpdesk_baseline_now` обновляет baseline без Telegram notifications.
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
Кнопка `Открыть заявку` не отправляется: GLPI/helpdesk URL внутренний и остаётся только в event data.
Reminder/hide buttons не входят в MVP.

## Dedup/status

Таблицы:

- `helpdesk_email_events`;
- `helpdesk_imap_mailbox_state`.

Дедупликация:

- partial unique `message_id`;
- partial unique `(folder, imap_uid)`.

`/status` показывает HelpDesk IMAP section без live IMAP connect:

- enabled/configured;
- host configured/missing;
- port;
- ssl;
- masked username;
- folder;
- telegram chat id configured/missing;
- missing config keys;
- last check;
- last success;
- last error;
- baseline set/not set;
- last seen uid;
- mailbox last check/success/error;
- processed last 24h;
- pending notifications.

Hotfix note: для старых IMAP серверов, которые падают на TLS handshake с `DH_KEY_TOO_SMALL`, client делает точечный retry с legacy OpenSSL `SECLEVEL=1`. Остальные TLS ошибки не даунгрейдятся автоматически.

## Ограничения

- один mailbox only;
- нет email replies;
- нет удаления писем;
- нет mark-seen по умолчанию;
- нет OCR/RAG;
- нет multi-mailbox UI;
- нет Smart Watcher;
- нет live destructive Telegram calls.

## Stage 4L-2 extension

Stage 4L-2 HelpDesk Ticket Workflow добавляет только рабочее состояние Telegram-карточек поверх уже сохранённых `helpdesk_email_events`:

- новая заявка получает work item `waiting_ack` в `helpdesk_ticket_work_items`;
- карточка новой заявки получает кнопку `В работу`;
- команда `/ticket` показывает заявки в статусе `in_work`;
- callbacks `hd_ticket:take:<id>`, `hd_ticket:done:<id>`, `hd_ticket:snooze:<id>:60` меняют только work item state;
- worker cron `remind_helpdesk_tickets` напоминает каждые 10 минут для `waiting_ack` и каждые 30 минут для `in_work`;
- алиас `/tiket` не добавлен и не закрепляется как API.

Эта extension не меняет IMAP чтение: нет email replies, удаления писем, destructive IMAP calls, Railway Variables changes или внутренней ticket URL button.

## Live checklist

1. Держать `HELPDESK_IMAP_ENABLED=false`, если старый поток ещё идёт.
2. Deploy после manual merge в `main`.
3. Выполнить `/helpdesk_baseline_now`.
4. Включить HelpDesk IMAP.
5. Проверить `/status`: baseline `set`, last seen uid заполнен.
6. Отправить новое GLPI письмо или комментарий от `HELPDESK_IMAP_FROM_FILTER`.
7. Проверить одну Telegram карточку в `HELPDESK_TELEGRAM_CHAT_ID`.
8. Дождаться следующего polling interval и проверить, что duplicate card не пришла.
9. Проверить, что кнопки `Открыть заявку` нет.
10. При `HELPDESK_MARK_SEEN=false` проверить, что письмо осталось unread.
11. Для Stage 4L-2 нажать `В работу`, проверить появление заявки в `/ticket`, затем `Отложить 1ч` и `Готово`.

## Readiness

```bash
uv run --python 3.12 --extra dev python scripts/smoke_helpdesk_imap_readiness.py
```

Ожидаемый verdict:

```text
PASS_HELPDESK_IMAP_READINESS
```
