# Hotfix Access Settings FSM Input Report

## Symptom

После `/settings -> Доступ -> Пользователи -> Добавить пользователя` бот показывал prompt:

```text
Отправьте Telegram user ID.
Можно добавить подпись через пробел:

59144850 Александр
```

Но следующий private text, например:

```text
5117224471 291844566
```

обрабатывался обычным private LLM handler. В результате создавался `process_llm_message` job, а пользователь видел `Принял. Готовлю ответ.` вместо добавления allowlist entries.

## Root Cause

Root cause: `POST /telegram/webhook` создавал новый aiogram `Dispatcher` через `build_dispatcher(settings)` для каждого webhook update, если `app.state.dispatcher` не был задан.

Access settings FSM использует aiogram `MemoryStorage`, привязанный к конкретному `Dispatcher`. Callback update `settings:access:user:add` ставил state в одном Dispatcher instance, а следующий message update попадал в новый Dispatcher instance с пустым FSM storage. Поэтому `StateFilter(TelegramAccessInput.add_user)` не видел active state, и message доходил до generic private LLM handler.

Это не была проблема prompt, прав доступа или LLM handler logic.

## Fix

- Webhook route теперь сохраняет lazy-created Dispatcher в `request.app.state.dispatcher`.
- Callback update и следующий message update используют один Dispatcher и один FSM storage.
- Regression tests проходят через настоящий `/telegram/webhook`: callback update, затем text message update.
- Access input parser поддерживает один ID с label и несколько ID без label.

## Supported Input Formats

Один user ID с подписью:

```text
5117224471 Александр
```

Несколько user IDs через пробел:

```text
5117224471 291844566
```

Несколько IDs по строкам:

```text
5117224471
291844566
```

Group IDs работают аналогично. Group ID может быть отрицательным:

```text
-5437860232 Домашний чат
```

## Cancel

`/cancel` очищает access FSM state. После отмены обычное private message снова идёт в regular private LLM flow.

## Live Verification Checklist

- Открыть `/settings -> Доступ -> Пользователи -> Добавить пользователя`.
- Отправить `5117224471 Александр`.
- Убедиться, что нет `Принял. Готовлю ответ.`.
- Убедиться, что user появился в списке.
- Повторить add flow и отправить `5117224471 291844566`.
- Убедиться, что оба IDs появились в списке.
- Проверить `/cancel` в access input state.
- После `/cancel` отправить обычный private вопрос и убедиться, что regular assistant отвечает как раньше.
