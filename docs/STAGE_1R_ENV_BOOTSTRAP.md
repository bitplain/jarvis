# Stage 1R ENV Bootstrap

## Назначение

`scripts/bootstrap_real_env.py` помогает подготовить локальный `.env` для реальных Stage 1R smoke-проверок без вывода секретов в консоль, отчёты или git diff.

По умолчанию скрипт работает в dry-run режиме:

```bash
uv run --python 3.12 --extra dev python scripts/bootstrap_real_env.py
uv run --python 3.12 --extra dev python scripts/bootstrap_real_env.py --dry-run
```

Для записи недостающих значений в `.env` нужен явный флаг:

```bash
uv run --python 3.12 --extra dev python scripts/bootstrap_real_env.py --apply
```

## Что генерируется локально

- `TELEGRAM_WEBHOOK_SECRET` — 48 или 64 символа из `A-Z`, `a-z`, `0-9`, `_`, `-`.
- `ADMIN_API_TOKEN` — локальный bearer token для admin endpoint.

Значения не печатаются. В выводе допустимы только статусы `<set>`, `<generated>`, `<derived>`, `<missing>`, `<invalid>`.

## Что получается через API

- `TELEGRAM_BOT_USERNAME` берётся из Telegram Bot API `getMe`, если задан `TELEGRAM_BOT_TOKEN`.
- `ADMIN_TELEGRAM_IDS` может быть получен через Telegram Bot API `getUpdates`, если пользователь уже отправил боту личное сообщение.
- `OPENROUTER_MODEL` выбирается через OpenRouter `/api/v1/models`, затем проверяется коротким chat completion smoke.
- `YANDEX_AI_MODEL` проверяется коротким chat completion smoke через Yandex OpenAI-compatible API.

API keys, Telegram token, Authorization headers и реальные env values не выводятся.

## ADMIN_TELEGRAM_IDS и ручной /start

`getUpdates` видит только updates, которые Telegram ещё отдаёт polling API. Если пользователь ещё не писал боту, скрипт вернёт `BLOCKED_NEEDS_MANUAL_TELEGRAM_START`.

Что сделать:

1. Открыть Telegram.
2. Найти своего бота.
3. Отправить ему `/start` в личке.
4. Повторно запустить:

```bash
uv run --python 3.12 --extra dev python scripts/bootstrap_real_env.py --apply
```

Если webhook уже установлен, `getUpdates` может не работать. Скрипт не удаляет webhook автоматически. Для явного временного удаления webhook можно использовать:

```bash
uv run --python 3.12 --extra dev python scripts/bootstrap_real_env.py --apply --delete-webhook-for-getupdates
```

По умолчанию pending updates сохраняются (`drop_pending_updates=False`). Если их нужно явно удалить, используется отдельный флаг:

```bash
uv run --python 3.12 --extra dev python scripts/bootstrap_real_env.py --apply --delete-webhook-for-getupdates --drop-pending-updates
```

## Yandex model

`YANDEX_AI_BASE_URL` автоматически выставляется в:

```env
YANDEX_AI_BASE_URL=https://ai.api.cloud.yandex.net/v1
```

Для автоподбора `YANDEX_AI_MODEL` нужен `YANDEX_AI_FOLDER_ID`. Скрипт пробует:

```text
gpt://<YANDEX_AI_FOLDER_ID>/qwen3-235b-a22b-fp8/latest
gpt://<YANDEX_AI_FOLDER_ID>/gpt-oss-120b/latest
```

Если folder id отсутствует или оба кандидата недоступны, нужно указать model URI вручную из Yandex AI Studio.

## Проверка готовности

После bootstrap выполнить dry-run:

```bash
uv run --python 3.12 --extra dev python scripts/bootstrap_real_env.py --dry-run
```

Готовый `.env` должен завершиться verdict `PASS_STAGE_1R_ENV_READY`. Если verdict заблокирован, следовать sanitized notes из вывода, не копируя секреты в отчёты.
