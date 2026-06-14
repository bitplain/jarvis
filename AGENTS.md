# Правила проекта Jarvis

## Язык и стиль

- Вся документация, stage-отчёты, комментарии к задачам и ответы бота пользователю пишутся на русском языке.
- Пользовательские ответы Telegram-бота должны быть только на русском.
- Если бот не знает ответ, он честно говорит, что не знает, и не выдумывает факты.

## Безопасность

- Нельзя хардкодить Telegram token, LLM API keys, пароли, model IDs, Telegram IDs и другие секреты.
- Все секреты задаются только через `.env` или GitHub Secrets.
- `.env` не должен попадать в git.
- В логах нельзя печатать Telegram token, LLM API keys, Authorization headers, пароли и реальные env secrets.

## Stage 1 границы

- GitHub repository не создаётся и ничего не пушится до отдельной команды.
- Secretary Mode и Mini App в Stage 1/2 не реализуются полностью.
- Business/Secretary код должен оставаться явным stub/no-op или выбрасывать `NotImplementedError`, чтобы его нельзя было принять за готовую функцию.
- Реальный Telegram/LLM smoke без настоящих env-секретов считается `BLOCKED_NEEDS_REAL_ENV`, а не успехом.
- Stage 1R env bootstrap может генерировать только локальные секреты в `.env`, выводить только sanitized status и никогда не коммитить реальные значения `.env`.

## Stage 2 Guest Mode

- Guest Mode обрабатывает только Telegram update type `guest_message`.
- Ответ Guest Mode отправляется только финальным `answerGuestQuery`.
- В Guest Mode запрещены streaming, `sendMessageDraft`, обычная chat memory и постоянная память чужого guest-чата.
- Если `guest_query_id` отсутствует, бот не отвечает и сохраняет только диагностическое событие.
- По умолчанию `GUEST_MODE_ENABLED=false` и `GUEST_MODE_ADMIN_ONLY=true`.
- Если Telegram не передал caller user id, Guest Mode отвечает отказом владельца и не вызывает LLM.
- Guest Mode учитывает только текст guest-вызова и replied message, если Telegram его передал.
- Обычный private/group бот остаётся доступен только `ADMIN_TELEGRAM_IDS`.
- Обычное сообщение в личке или группе не считается Guest Mode smoke.

## Stage 2R Polling Smoke

- Для локального Mac real smoke без публичного HTTPS URL используется polling через `scripts/run_polling.py`.
- Перед polling webhook обязательно удаляется через Telegram `deleteWebhook`.
- `drop_pending_updates` по умолчанию должен быть `false`; включать drop можно только явным флагом `--drop-pending-updates`.
- Readiness script `scripts/smoke_polling_readiness.py` не должен вызывать `getUpdates`, чтобы не съесть ручной `guest_message`.
- Polling smoke не использует tunnel и не засчитывает обычные `message`/group mention updates как Guest Mode.

## Проверки

Перед финальным отчётом выполнять:

```bash
uv run --python 3.12 --extra dev ruff check .
uv run --python 3.12 --extra dev mypy app
uv run --python 3.12 --extra dev pytest -q
docker compose build
docker compose up -d
docker compose ps
docker compose logs --tail=100 api
docker compose logs --tail=100 worker
docker compose exec api alembic upgrade head
docker compose exec api pytest -q
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8000/ready
uv run --python 3.12 --extra dev python scripts/smoke_llm.py
git status --short
```

## Remote AGENTS sync

Серверные/live project paths в этом репозитории не заведены.

`remote AGENTS sync = N/A until server/live paths exist`
