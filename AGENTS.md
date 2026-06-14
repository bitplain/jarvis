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

## Stage 3A Business Mode

- Business Mode по умолчанию выключен: `BUSINESS_MODE_ENABLED=false`.
- Ответы от имени Telegram Business account по умолчанию запрещены: `BUSINESS_REPLY_ENABLED=false`.
- Stage 3A не включает постоянный autonomous auto-reply и не отвечает всем входящим business-сообщениям.
- Ручной test reply разрешён только при `BUSINESS_MODE_ENABLED=true`, `BUSINESS_REPLY_ENABLED=true`, `BUSINESS_ADMIN_ONLY=true`, owner из `ADMIN_TELEGRAM_IDS`, активном connection, `can_reply=true` и trigger `BUSINESS_REPLY_TRIGGER`.
- Business Mode не использует обычную chat memory и Guest Mode memory; используется отдельная business-memory по `business_connection_id + chat_id`.
- В отчётах и логах нельзя выводить полный `business_connection_id`, Telegram IDs и приватный текст business-сообщений.
- Readiness script `scripts/smoke_business_readiness.py` не должен вызывать `getUpdates`, чтобы не съесть ручные business updates до polling runner.
- Real Business Mode smoke засчитывается только если пришли настоящие `business_connection` и `business_message`, ответ отправлен через `business_connection_id`, а БД подтвердила записи.

## Stage 3A-R Regular Assistant Mode

- Regular Assistant Mode — основной путь для обычного Telegram-аккаунта.
- Он работает через private chat с ботом, group mode при добавлении бота в группу, Guest Mode через `@bot_username`, forwarded-message assistant и draft reply assistant.
- Bot API не может читать личные входящие сообщения обычного пользователя и не может отвечать от имени обычного пользователя без Telegram Business / Secretary connection.
- Business / Secretary Mode остаётся optional advanced mode: требует Telegram Business / Secretary connection, `business_connection`, `can_reply` и отправку через `business_connection_id`.
- Нельзя писать в документации или ответах, что Secretary Mode работает без Business account.
- Draft Reply Mode возвращает только черновик, который пользователь сам копирует и отправляет.
- Forwarded Message Assistant работает только с текстом, который пользователь явно переслал боту.
- Group Assistant отвечает только на mention или reply на сообщение бота; не обещать чтение всей истории группы.
- Readiness script `scripts/smoke_regular_readiness.py` не требует Business account и должен считать Business Mode optional/disabled нормальным состоянием.

## Stage 3A-R-LIVE Regular Assistant Smoke

- Live smoke для group assistant засчитывается только в настоящей Telegram group/supergroup, где бот добавлен участником.
- Вызов `@bot_username` в чужом чате, который приходит как Telegram `guest_message`, относится к Guest Mode и не засчитывается как group assistant smoke.
- Group plain message без mention/reply должен быть проигнорирован без LLM job и без записи в regular memory.
- Group mention/reply smoke должен подтверждаться обычным `message` update, записью regular memory и worker job `process_llm_message(private=false)`.
- Если BotFather Privacy Mode не доставляет обычный group mention в Bot API, mention smoke считается blocked до отключения privacy mode или другой настройки доставки updates; это нельзя засчитывать как PASS.
- Команды `/summary`, `/draft_reply`, `/translate`, `/factcheck` должны принимать inline-аргумент после команды, включая форму `/command@bot_username`, а при пустом аргументе использовать доступный сохранённый контекст или честно просить контекст.

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
uv run --python 3.12 --extra dev python scripts/smoke_polling_readiness.py
uv run --python 3.12 --extra dev python scripts/smoke_regular_readiness.py
git status --short
```

## Remote AGENTS sync

Серверные/live project paths в этом репозитории не заведены.

`remote AGENTS sync = N/A until server/live paths exist`
