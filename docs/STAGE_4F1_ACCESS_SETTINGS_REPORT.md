# Stage 4F-1 Access Settings Report

## Цель

Stage 4F-1 добавляет управление доступом к Jarvis через Telegram `/settings -> Доступ`, чтобы разрешённых пользователей и группы можно было добавлять по Telegram ID без правки `.env`.

## Где открыть

1. Написать боту `/settings`.
2. Нажать `Доступ`.
3. Открыть `Пользователи` или `Группы`.

Управлять доступом могут только главные админы из `ADMIN_TELEGRAM_IDS`.

## Как узнать ID

Команда `/whoami` доступна всем.

В private она показывает:

```text
Ваш Telegram user ID: 59144850
Тип чата: private
Telegram chat ID: 59144850
```

В group/supergroup она отвечает reply-сообщением, показывает user ID, chat ID, тип чата и статус разрешения только для текущего пользователя и текущей группы.

## Как добавить пользователя

В `/settings -> Доступ -> Пользователи` нажать `Добавить пользователя` и отправить:

```text
59144850 Александр
```

Подпись после пробела optional. User ID должен быть положительным integer.

## Как добавить группу

В `/settings -> Доступ -> Группы` нажать `Добавить группу` и отправить:

```text
-5437860232 Домашний чат
```

Group chat ID хранится как bigint, поэтому отрицательные supergroup IDs поддерживаются.

## Env admin vs DB allowed user

- `ADMIN_TELEGRAM_IDS` остаются главными админами из env.
- Env admin всегда имеет доступ и может управлять `/settings`.
- Записи в `telegram_access_entries` дают доступ, но не делают пользователя admin.
- Allowed user не может открывать или менять `/settings`.
- Env admins не переносятся в таблицу автоматически.

## Правила групп

Если список разрешённых групп пустой, сохраняется старая совместимость: разрешённый пользователь может вызвать Jarvis в любой группе через mention/reply.

После добавления хотя бы одной группы включается group allowlist mode: для group response нужны и разрешённый пользователь, и разрешённая группа.

Неизвестные пользователи:

- в private получают `Доступ запрещён.`;
- в group/supergroup молча игнорируются.

## Что не входит

- Prompt Profiles.
- Shopping List.
- Reminders.
- Memory.
- Smart Watcher.

## Local readiness

Без секретов:

```bash
uv run --python 3.12 --extra dev python scripts/smoke_access_settings_readiness.py
```

Ожидаемый verdict:

```text
PASS_ACCESS_SETTINGS_READINESS
```

## Live verification checklist

- `/whoami` в private показывает user ID и chat ID.
- `/whoami` в group показывает user ID и group chat ID reply-сообщением.
- `/settings -> Доступ` открывается у env admin.
- Env admin добавляет тестовый user ID.
- Тестовый user пишет в private и получает обычный ответ Jarvis.
- Env admin удаляет тестовый user ID.
- Unknown group user молча игнорируется.
- Authorized group mention/reply отвечает один раз.
