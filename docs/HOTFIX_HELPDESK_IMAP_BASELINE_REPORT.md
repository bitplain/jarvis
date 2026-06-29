# Hotfix HelpDesk IMAP Baseline Report

## Цель

Остановить рассылку старых HelpDesk/GLPI писем из INBOX после включения IMAP polling.

## Поведение

- Первый успешный poll без `helpdesk_imap_mailbox_state` сохраняет baseline: `last_seen_uid = current max UID`.
- Старые письма до baseline не отправляются в Telegram.
- После baseline worker читает только письма с UID больше `last_seen_uid`.
- Новый комментарий к старой заявке отправляется, потому что IMAP выдаёт ему новый UID.
- Если IMAP `UIDVALIDITY` изменился, worker ставит новый baseline на current max UID и не рассылает весь mailbox заново.

## Ручная команда

Admin-only команда:

```text
/helpdesk_baseline_now
```

Она подключается к IMAP, сохраняет текущий max UID и отвечает:

```text
HelpDesk baseline обновлён.
Старые письма до UID <N> больше не будут отправляться.
```

Если HelpDesk IMAP выключен или не настроен:

```text
HelpDesk IMAP не настроен.
```

## Telegram карточка

Кнопка `Открыть заявку` удалена из карточки по умолчанию.
Внутренний ticket URL остаётся в parsed/event данных, но не показывается как Telegram URL button.

## Безопасность

- Railway Variables не меняются кодом.
- IMAP password и Telegram token не печатаются.
- Полное тело письма не логируется.
- Письма не удаляются.
- Старые письма не помечаются прочитанными.
- `BODY.PEEK[]` остаётся read-only чтением тела письма.
- `HELPDESK_MARK_SEEN=false` остаётся default.

## Live checklist

1. Держать `HELPDESK_IMAP_ENABLED=false`, пока flood не остановлен.
2. Merge вручную после audit.
3. Deploy.
4. Выполнить `/helpdesk_baseline_now`.
5. Включить HelpDesk IMAP.
6. Проверить `/status`: baseline `set`, last seen uid заполнен.
7. Отправить новое GLPI email/comment.
8. Проверить, что пришла одна Telegram карточка.
9. Следующий poll не должен прислать duplicate.
10. Кнопки `Открыть заявку` нет.
