# Stage 4L-3 HelpDesk Vacation Mode

## Итог

Stage 4L-3 добавляет режим отпуска для одного HelpDesk/GLPI mailbox.
Режим не отключает IMAP polling: новые письма продолжают читаться через `BODY.PEEK[]`, events и work items сохраняются, baseline/high-water-mark и дедуп работают как раньше.

Когда отпуск включён, автоматические Telegram карточки и HelpDesk reminders подавляются.
Подавление фиксируется в `helpdesk_email_events` как `notify_status=suppressed_vacation`, `error_code=vacation`, поэтому это не считается failed notification.

## Данные

Новая таблица:

- `helpdesk_vacation_state`;
- один row со scope `default`;
- `enabled`, `enabled_at`, `disabled_at`;
- `last_reviewed_at`;
- `enabled_by_user_id`, `disabled_by_user_id`;
- `created_at`, `updated_at`.

`enabled_at` задаёт начало текущего отпускного окна.
`last_reviewed_at` — cursor ручного просмотра.
`disabled_at` закрывает последнее отпускное окно после выключения.

## Поведение

Когда отпуск включён:

- IMAP polling продолжает работу;
- новая GLPI заявка или комментарий сохраняется;
- work item создаётся или обновляется для новой заявки;
- Telegram карточка не отправляется;
- `waiting_ack` reminders не отправляются;
- `in_work` reminders не отправляются;
- `last_seen_uid` продвигается безопасно, чтобы не вызвать старый flood.

Когда отпуск выключается:

- накопленные отпускные события остаются review-only;
- старые карточки и reminders не рассылаются задним числом;
- active HelpDesk reminders переносятся на `now + reminder_interval_minutes`;
- новые будущие события снова уведомляются обычным способом.

## Ручной просмотр

Команда `/helpdesk_vacation` показывает статус и кнопки.
Кнопка `Показать новые за отпуск` группирует события по GLPI ticket id.

Первый просмотр после включения показывает всё с `enabled_at`.
Следующие просмотры показывают только события после `last_reviewed_at`.
Cursor обновляется только после успешной отправки review message в Telegram.
Если отправка review падает, cursor не двигается, чтобы события не потерялись.

## UX

Команды:

- `/helpdesk_vacation`;
- `/helpdesk_vacation_on`;
- `/helpdesk_vacation_off`.

В `/settings -> HelpDesk` доступны:

- `Включить отпуск`;
- `Выключить отпуск`;
- `Показать новые за отпуск`;
- `Назад`;
- `Закрыть`.

Доступ проверяется по HelpDesk ticket control policy: env admin или allowed user/group.
Unknown group users не могут включать отпуск, выключать отпуск или запускать review.

## `/status`

`/status` читает только Redis/PostgreSQL diagnostics и не подключается к IMAP live.
В HelpDesk block добавлены sanitized поля:

- vacation mode;
- vacation since;
- vacation new since start;
- vacation new since last review;
- vacation last reviewed.

Secrets, Telegram IDs, полный email body, полные email addresses, IMAP password, Telegram token и Authorization headers не выводятся.

## Safety

- Railway Variables не меняются.
- Нет push в `main`.
- Нет merge PR.
- Нет destructive Telegram/IMAP calls.
- Нет email replies.
- Нет удаления писем.
- MVP не помечает письма прочитанными при `HELPDESK_MARK_SEEN=false`.
- Vacation mode не сбрасывает baseline и не вызывает old mailbox flood.

## Self-audit

VACATION_SUPPRESSION_SAFETY: PASS
NO_BACKLOG_FLOOD: PASS
REVIEW_CURSOR_SAFETY: PASS
REMINDER_SUPPRESSION_SAFETY: PASS
CALLBACK_ACCESS_SAFETY: PASS
HELPDESK_REGRESSION: PASS
REGRESSION_CHECKS: PASS

## Live checklist

1. Merge вручную.
2. Deploy.
3. Выполнить `/helpdesk_vacation_on`.
4. Отправить или дождаться GLPI email.
5. Проверить, что automatic card/reminder не пришли.
6. Выполнить `/helpdesk_vacation` и нажать `Показать новые за отпуск`.
7. Первый review показывает накопленные заявки.
8. Второй review не показывает дублей.
9. Отправить ещё один GLPI email.
10. Review показывает только новый item.
11. Выполнить `/helpdesk_vacation_off`.
12. Проверить, что backlog flood не пошёл.
13. Проверить, что будущие новые tickets уведомляются обычным способом.
