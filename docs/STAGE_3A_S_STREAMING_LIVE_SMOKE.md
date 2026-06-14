# Stage 3A-S Streaming Live Smoke

Дата: 2026-06-14

## Статус

Live smoke пока не выполнен.

Текущий допустимый verdict до ручного Telegram smoke:

`BLOCKED_NEEDS_MANUAL_STREAMING_TEST`

## Подготовка runtime

```bash
docker compose up -d
docker compose ps
docker compose exec api alembic upgrade head
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8000/ready
uv run --python 3.12 --extra dev python scripts/smoke_streaming_readiness.py
```

## Polling runner

Перед polling webhook должен быть удалён самим runner/readiness path без `drop_pending_updates=true`.

```bash
uv run --python 3.12 --extra dev python scripts/run_polling.py
```

Не запускать readiness scripts, которые вызывают `getUpdates`: `scripts/smoke_streaming_readiness.py`, `scripts/smoke_polling_readiness.py` и `scripts/smoke_group_readiness.py` не должны съедать ручные updates.

## Private draft streaming smoke

Пользователь отправляет в личку боту:

```text
Напиши длинный ответ на 8 пунктов: как правильно обслуживать PostgreSQL в небольшом проекте
```

Засчитывать только если подтверждены факты:

- draft preview появился в Telegram client или logs показывают successful `sendMessageDraft`;
- draft updates throttled, не на каждый token;
- финальный `sendMessage` пришёл;
- в БД сохранён один final assistant response;
- нет дублей assistant response;
- если Telegram draft API/client недоступен, fallback сработал и ошибка зафиксирована sanitized.

## Group fallback smoke

В настоящей test group/supergroup, где бот добавлен участником, отправить:

```text
@bot_username дай длинный ответ на 6 пунктов: зачем нужен DNS
```

Засчитывать только если подтверждены факты:

- update пришёл как обычный `message`, не `guest_message`;
- worker job `process_llm_message(private=false)`;
- provisional `Думаю...` появился;
- provisional message редактировался накопленным текстом с throttling;
- финальный ответ появился через edit или final send fallback;
- regular group rows есть в БД;
- `guest_messages_stub` и business tables не загрязнены этим smoke.

## Guest no-streaming smoke

Guest Mode не должен использовать streaming.

Минимальная проверка:

- guest update обрабатывается final-only;
- ответ отправлен через `answerGuestQuery`;
- нет `sendMessageDraft`;
- нет `TelegramGroupEditSink`;
- нет regular group/private memory contamination.

## Evidence template

Заполнить после ручного smoke:

| Проверка | Результат | Evidence |
| --- | --- | --- |
| Private draft preview/API | PENDING | |
| Private final sendMessage | PENDING | |
| Private DB final-only | PENDING | |
| Group provisional | PENDING | |
| Group throttled edit | PENDING | |
| Group `private=false` job | PENDING | |
| Group DB rows | PENDING | |
| Guest no-streaming | PENDING | |

## Verdict после smoke

Выбрать только один:

- `PASS_STAGE_3A_S_STREAMING_READY`
- `PARTIAL_STAGE_3A_S_PRIVATE_DRAFT_UNAVAILABLE`
- `PARTIAL_STAGE_3A_S_GROUP_FALLBACK_FAILED`
- `PARTIAL_STAGE_3A_S_PROVIDER_STREAMING_LIMIT`
- `BLOCKED_NEEDS_MANUAL_STREAMING_TEST`
- `PARTIAL_STAGE_3A_S_DB_CHECK_FAILED`
